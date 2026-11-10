"""Write local, review-only city GeoJSON from private qualified optical rays."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory

from fiona.transform import transform

from scripts.tsr.collection.estimate_sign_poses import (
    MAX_HEADING_ERROR_DEG,
    MAX_MOBILE_SOURCE_POSITION_ERROR_M,
    MAX_POSITION_RADIUS_M,
    MAX_RAY_POSITION_ERROR_M,
    METRIC,
    WGS84,
    consolidate_sequences,
    delta_angle,
    digest,
    estimate,
    image_bearing_candidate,
    project,
)
from scripts.tsr.collection.image_approach import image_approach
from scripts.tsr.collection.osm_sign_heading import RoadHeadingIndex
from scripts.tsr.collection.panoramax_sequence_bridge import (
    MAX_CAMERA_DISTANCE_M,
    MAX_CAMERA_HEADING_DELTA_DEG,
    bridge_features,
    rebuild_positions,
)
from scripts.tsr.collection.sign_identities import (
    identity_entry,
    load_identities,
    match_identities,
)
from scripts.tsr.collection.sign_panel_pose import panel_heading
from scripts.tsr.collection.travelled_way import TravelBundles


def read_private(path, limit, *, allow_empty=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_size > limit
            or not (allow_empty or info.st_size)
        ):
            raise ValueError("input must be a bounded private file")
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("private input grew beyond the size limit")
    return data


def write_private_json(path, document):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            document, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        handle.write("\n")


def area(value):
    ags, _, filename = value.partition(":")
    if not re.fullmatch(r"[0-9]{8}", ags) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", filename
    ):
        raise argparse.ArgumentTypeError("expected AGS:filename-stem")
    return ags, filename


def position_qualified_rays(records):
    """Withhold valid mobile source rays beyond the estimator's position limit."""
    qualified = []
    withheld = 0
    for row in records:
        error = row.get("horizontal_error_m")
        if (
            row.get("source") == "mobile"
            and type(error) in (int, float)
            and MAX_RAY_POSITION_ERROR_M < error <= MAX_MOBILE_SOURCE_POSITION_ERROR_M
        ):
            withheld += 1
        else:
            qualified.append(row)
    return qualified, withheld


def pan_candidate_images(records, boundary_file, areas):
    from commercial_backend.youspeed.sign_wfs_boundaries import AdministrativeBoundaries

    boundaries = AdministrativeBoundaries.load(boundary_file)
    qualified, _ = position_qualified_rays(records)
    estimates, _ = estimate(qualified)
    images = set()
    if estimates:
        eastings, northings = zip(*(fit.point for _, fit, _ in estimates))
        lons, lats = transform(METRIC, WGS84, eastings, northings)
        for (_, fit, _), lon, lat in zip(estimates, lons, lats):
            keys = boundaries.memberships(lon, lat).get("gemeinde_ags", ())
            if areas.intersection(keys):
                images.update(
                    ray.image.removeprefix("panoramax:")
                    for ray in fit.rays
                    if ray.source == "panoramax"
                )
    return sorted(images)


def panel_candidates(records, estimates, evidence, verified):
    if not evidence:
        return {}

    def source_key(row):
        return (
            f"{row['source']}:{row['observation_id']}",
            f"{row['source']}:{row['image_id']}",
        )

    eligible = {
        source_key(row): row["sign_code"]
        for row in records
        if verified is None or digest(row) in verified
    }
    groups = defaultdict(list)
    seen = set()
    for row in evidence:
        key = source_key(row)
        if key in seen:
            raise ValueError("duplicate panel observation")
        seen.add(key)
        groups[row["review_group_id"]].append(row)

    linked = defaultdict(list)
    for rows in groups.values():
        keys = {source_key(row) for row in rows}
        if not keys <= eligible.keys() or len({eligible[key] for key in keys}) != 1:
            continue
        # Manual same-face review can support a heading outside the positional
        # fit, but only with two exact source links and no competing fit.
        fits = [
            (fit, len(keys.intersection((ray.key, ray.image) for ray in fit.rays)))
            for _, fit, _ in estimates
        ]
        matches = [(fit, count) for fit, count in fits if count]
        if len(matches) == 1 and matches[0][1] >= 2:
            linked[matches[0][0].keys].append(rows)
    return {
        key: panel_heading(groups[0])
        for key, groups in linked.items()
        if len(groups) == 1
    }


def write_city_drafts(
    records,
    boundary_file,
    areas,
    output,
    id_key,
    *,
    confirmed=None,
    roads=None,
    panel_evidence=(),
    travel_bundles=None,
    private_panoramax=False,
    previous_identities=(),
    road_azimuth_fallback=False,
    panoramax_report=None,
):
    # The sibling analytics checkout owns the shared WFS field and boundary contracts.
    from commercial_backend.youspeed.sign_wfs_boundaries import AdministrativeBoundaries
    from commercial_backend.youspeed.sign_wfs_snapshot import FIELDS

    if len(id_key) < 32:
        raise ValueError("ID key must contain at least 32 private bytes")
    if len(dict(areas)) != len(areas) or len(
        {filename for _, filename in areas}
    ) != len(areas):
        raise ValueError("duplicate municipality code or filename")
    if output.exists() or output.is_symlink():
        raise FileExistsError("choose a new output directory for this review batch")
    if panoramax_report is not None and (
        not private_panoramax or confirmed is not None
    ):
        raise ValueError("sequence bridges require private Panoramax review")
    boundaries = AdministrativeBoundaries.load(boundary_file)
    records, uncertain_mobile = position_qualified_rays(records)
    estimates, diagnostics = estimate(records)
    if uncertain_mobile:
        diagnostics["mobile_rays_withheld_for_position_uncertainty"] = uncertain_mobile
    qualified_counts = Counter(row["source"] for row in records)
    verified = None
    if confirmed is not None:
        verified = {digest(row) for row in confirmed}
        qualified_counts = Counter(
            row["source"] for row in records if digest(row) in verified
        )
        selected = [
            row
            for row in estimates
            if all(ray.fingerprint in verified for ray in row[1].rays)
        ]
        diagnostics["fits_with_unconfirmed_source"] = len(estimates) - len(selected)
        estimates = selected
    prior_count = len(estimates)
    estimates = consolidate_sequences(estimates)
    diagnostics["cross_sequence_fits_consolidated"] = prior_count - len(estimates)
    groups = []
    if panoramax_report is not None:
        estimates, groups, bridge_diagnostics = rebuild_positions(
            records, panoramax_report, estimates
        )
        diagnostics.update(bridge_diagnostics)
    by_ags = {ags: [] for ags, _ in areas}
    sign_by_ray = {}
    panels = panel_candidates(records, estimates, panel_evidence, verified)
    identity_ledger = []
    if estimates:
        eastings, northings = zip(*(fit.point for _, fit, _ in estimates))
        lons, lats = transform(METRIC, WGS84, eastings, northings)
        selected = []
        for (code, fit, heading), lon, lat, (_, rotation) in zip(
            estimates, lons, lats, project(lons, lats)
        ):
            memberships = boundaries.memberships(lon, lat)
            keys = memberships.get("gemeinde_ags", ())
            if not set(keys).intersection(by_ags):
                continue
            selected.append((code, fit, heading, lon, lat, rotation, memberships))
            identity_ledger.append(identity_entry(code, fit, id_key))
        match_identities(identity_ledger, previous_identities)
        if len({row["id"] for row in identity_ledger}) != len(identity_ledger):
            raise ValueError("duplicate canonical sign identity")
        for (code, fit, heading, lon, lat, rotation, memberships), identity in zip(
            selected, identity_ledger
        ):
            identifier = identity["id"]
            sign_by_ray.update(dict.fromkeys(fit.keys, identifier))
            heading_text, heading_error, heading_method = None, None, None
            heading_arc = None
            visibility_candidate = None
            calibrated = all(ray.pose_basis == "calibrated" for ray in fit.rays)
            if heading:
                grid_heading, half_width, heading_method = heading
                true_heading = (grid_heading - rotation) % 360
                heading_arc = [
                    round((true_heading + delta) % 360, 3) % 360
                    for delta in (-half_width, half_width)
                ]
                if half_width <= MAX_HEADING_ERROR_DEG:
                    if calibrated:
                        heading_error = half_width
                        heading_text = f"{round(true_heading, 1) % 360:.1f}"
                    else:
                        visibility_candidate = (
                            round(true_heading, 1) % 360,
                            half_width,
                        )
            properties = dict.fromkeys(FIELDS)
            properties.update(
                id=identifier,
                stvo_nr=code[3:],
                ost=f"{fit.point[0]:.2f}",
                nord=f"{fit.point[1]:.2f}",
                azimut=heading_text,
                datum=max(ray.captured_at[:10] for ray in fit.rays),
                stack_order=0,
                sighting_count=len(fit.rays),
                sequence_count=len({ray.sequence for ray in fit.rays}),
                source_types=",".join(sorted({ray.source for ray in fit.rays})),
                position_status="coarse_review"
                if fit.radius > MAX_POSITION_RADIUS_M
                else "estimated",
                position_method="intersected_optical_rays",
                camera_pose_basis="calibrated" if calibrated else "assumed",
                position_radius_m=math.ceil(fit.radius * 10) / 10,
                heading_method=heading_method,
                heading_error_deg=heading_error,
                front_azimuth_arc_deg=heading_arc,
            )
            mobile_sightings = sum(ray.evidence_kind == "sighting" for ray in fit.rays)
            if mobile_sightings:
                properties["mobile_sighting_rays"] = mobile_sightings
            if visibility_candidate is not None:
                properties.update(
                    image_visibility_candidate_azimut_deg=visibility_candidate[0],
                    image_visibility_half_width_deg=visibility_candidate[1],
                )
            image_candidate = image_bearing_candidate(fit.rays)
            if image_candidate is not None:
                properties.update(
                    image_candidate_azimut_deg=round(
                        (image_candidate.heading - rotation) % 360, 1
                    )
                    % 360,
                    image_candidate_method="sequence_balanced_reverse_ray",
                    image_candidate_views=image_candidate.views,
                    image_candidate_sequences=image_candidate.sequences,
                    image_candidate_spread_deg=round(image_candidate.spread, 1),
                    image_bearing_allowance_deg=round(
                        image_candidate.bearing_allowance, 1
                    ),
                )
            panel = panels.get(fit.keys)
            if panel is not None and (
                heading is None
                or delta_angle(panel["azimut_deg"] + rotation, heading[0])
                <= panel["sensitivity_half_width_deg"] + heading[1]
            ):
                properties.update(
                    image_panel_candidate_azimut_deg=panel["azimut_deg"],
                    image_panel_candidate_method=panel["method"],
                    image_panel_candidate_views=panel["views"],
                    image_panel_sensitivity_half_width_deg=panel[
                        "sensitivity_half_width_deg"
                    ],
                )
            if roads is not None:
                road = roads.heading(
                    fit,
                    code,
                    lon,
                    lat,
                    heading,
                    approach=image_approach,
                    travel_bundles=travel_bundles,
                )
                properties.update(
                    osm_heading_status=(
                        "candidate_needs_image_corroboration"
                        if road.facing is not None and not road.corroborated
                        else road.status
                    ),
                    osm_way_id=road.way_id,
                    osm_way_side=road.side,
                    osm_candidate_azimut_deg=(
                        round((road.facing - rotation) % 360, 1) % 360
                        if road.facing is not None
                        else None
                    ),
                    osm_facing_options_deg=[
                        round((value - rotation) % 360, 1) % 360
                        for value in road.candidates
                    ],
                    image_approach_deg=(
                        round((road.image_travel - rotation) % 360, 1) % 360
                        if road.image_travel is not None
                        else None
                    ),
                    image_approach_method=road.image_method,
                )
                if road.recorded_travel is not None:
                    properties["recorded_approach_deg"] = (
                        round((road.recorded_travel - rotation) % 360, 1) % 360
                    )
                if (
                    heading_text is None
                    and road.facing is not None
                    and road.corroborated
                ):
                    properties.update(
                        azimut=f"{round((road.facing - rotation) % 360, 1) % 360:.1f}",
                        heading_method=road.method,
                    )
                if properties["azimut"] is None and road_azimuth_fallback:
                    fallback = roads.fallback(
                        fit, lon, lat, road.way_id, travel_bundles
                    )
                    if fallback is not None:
                        approach = round((fallback.approach - rotation) % 360, 1) % 360
                        properties.update(
                            azimut=f"{(approach + 180) % 360:.1f}",
                            heading_method=fallback.method,
                            heading_fallback_way_id=fallback.way_id,
                            heading_fallback_direction_basis=fallback.direction_basis,
                            heading_fallback_approach_deg=approach,
                            heading_fallback_distance_m=round(fallback.distance, 1),
                            heading_fallback_tangent_ambiguous=fallback.tangent_ambiguous,
                        )
            for field in ("gemeinde_ags", "kreis_ags", "stadtbezirk_id"):
                properties[field] = "|".join(memberships.get(field, ())) or None
            feature = {
                "type": "Feature",
                "id": f"verkehrszeichen.{identifier}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": properties,
            }
            for ags in memberships.get("gemeinde_ags", ()):
                if ags in by_ags:
                    by_ags[ags].append(feature)
    totals = {}
    with TemporaryDirectory(prefix=".sign-pose-draft-", dir=output.parent) as temporary:
        staging = Path(temporary) / "cities"
        staging.mkdir(mode=0o700)
        for ags, filename in areas:
            features = sorted(by_ags[ags], key=lambda item: item["id"])
            counts = Counter(
                {"position_estimates": len(features), "heading_estimates": 0}
            )
            counts["heading_estimates"] = sum(
                f["properties"]["azimut"] is not None for f in features
            )
            if road_azimuth_fallback:
                counts["road_fallback_estimates"] = sum(
                    "heading_fallback_way_id" in f["properties"] for f in features
                )
            if panoramax_report is not None:
                bridges = bridge_features(groups, boundaries, ags, sign_by_ray, id_key)
                counts["camera_bridge_groups"] = len(bridges)
                counts["camera_bridge_groups_with_sign_estimate"] = sum(
                    feature["properties"]["sign_id"] is not None for feature in bridges
                )
                counts["coarse_position_estimates"] = sum(
                    f["properties"]["position_status"] == "coarse_review"
                    for f in features
                )
                write_private_json(
                    staging / f"{filename}-sequence-bridges.geojson",
                    {
                        "type": "FeatureCollection",
                        "name": "panoramax_sequence_bridges",
                        "gemeinde_ags": ags,
                        "metadata": {
                            "status": "private_sequence_association_review",
                            "geometry_role": "camera_positions",
                            "camera_distance_less_than_m": MAX_CAMERA_DISTANCE_M,
                            "camera_heading_difference_at_most_deg": MAX_CAMERA_HEADING_DELTA_DEG,
                        },
                        "features": bridges,
                    },
                )
            totals[ags] = dict(counts)
            document = {
                "type": "FeatureCollection",
                "name": "verkehrszeichen",
                "gemeinde_ags": ags,
                "numberMatched": len(features),
                "numberReturned": len(features),
                "metadata": {
                    "status": "private_estimation_draft",
                    "qualified_ray_counts": dict(qualified_counts),
                    "review_required": True,
                    "identity_policy": "canonical-sign-v1",
                    **(
                        {"azimuth_fallback_policy": "opposite_local_osm_approach"}
                        if road_azimuth_fallback
                        else {}
                    ),
                    **(
                        {"panoramax_access_policy": "owner_review_all_visibility"}
                        if private_panoramax
                        else {}
                    ),
                    "azimuth_convention": "sign front normal clockwise from true north",
                    "uncertainty": "conditional on camera, association, visibility and panel-model assumptions",
                    **(
                        {"osm_heading_source": roads.source}
                        if roads is not None
                        else {}
                    ),
                },
                "features": features,
            }
            write_private_json(staging / f"{filename}.geojson", document)
        write_private_json(
            staging / "sign-identities.json",
            {"schema_version": 1, "signs": identity_ledger},
        )
        staging.rename(output)
    return {"municipalities": totals, "fit_diagnostics": diagnostics}


def load_batches(paths, *, private_panoramax=False):
    rows = []
    needs_confirmation = False
    for source in paths:
        lines = source.suffix == ".jsonl"
        data = read_private(source, 64 * 1024**2, allow_empty=lines)
        if lines:
            batch = [json.loads(line) for line in data.splitlines() if line.strip()]
        else:
            document = json.loads(data)
            batch = document.get("rays") if isinstance(document, dict) else document
            private_marker = (
                isinstance(document, dict)
                and document.get("private_panoramax_review") is True
            )
            if private_marker and not private_panoramax:
                raise ValueError("owner-review inputs require --private-panoramax-rays")
            if private_panoramax and (
                not private_marker or document.get("origin_rechecked") is not False
            ):
                raise ValueError("expected an owner-review Panoramax ray document")
            if isinstance(document, dict) and document.get("origin_rechecked") is False:
                needs_confirmation |= not private_panoramax
        if not isinstance(batch, list):
            raise ValueError("each private ray batch must contain a JSON array of rays")
        if private_panoramax and (
            lines
            or any(
                not isinstance(row, dict) or row.get("source") != "panoramax"
                for row in batch
            )
        ):
            raise ValueError(
                "owner-review inputs must be JSON containing only Panoramax rays"
            )
        if not private_panoramax and any(
            isinstance(row, dict)
            and row.get("source") == "panoramax"
            and (
                any(
                    row.get(key, "anyone") != "anyone"
                    for key in (
                        "item_visibility",
                        "picture_visibility",
                        "sequence_visibility",
                    )
                )
                or any(
                    row.get(key, "ready") != "ready"
                    for key in ("picture_status", "sequence_status")
                )
            )
            for row in batch
        ):
            raise ValueError(
                "restricted Panoramax rows require --private-panoramax-rays"
            )
        rows.extend(batch)
        if len(rows) > 50_000:
            raise ValueError("choose a smaller area for batches above 50000 rays")
    return rows, needs_confirmation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rays", type=Path, action="append", default=[])
    parser.add_argument(
        "--private-panoramax-rays",
        type=Path,
        action="append",
        default=[],
        help="Owner-review Panoramax documents from the authoritative corpus, regardless of visibility",
    )
    parser.add_argument(
        "--panoramax-bridge-report",
        type=Path,
        help="Original owner-only JSONL report for the same Panoramax ray snapshot",
    )
    parser.add_argument(
        "--confirmed-rays",
        type=Path,
        action="append",
        help="Withhold fits with any ray absent from these requalified inputs",
    )
    parser.add_argument("--id-key-file", type=Path)
    parser.add_argument(
        "--previous-identities",
        type=Path,
        help="Owner-only identity ledger from the previous city batch",
    )
    parser.add_argument(
        "--panel-evidence",
        type=Path,
        help="Owner-only JSON array of reviewed rectangular panel corners",
    )
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument(
        "--osm-road-graph",
        type=Path,
        help="Pinned original OSM road graph for private heading fallbacks",
    )
    parser.add_argument(
        "--road-azimuth-fallback",
        action="store_true",
        help="Fill remaining private draft azimuths opposite the selected local OSM way",
    )
    parser.add_argument(
        "--travel-bundle",
        type=Path,
        action="append",
        default=[],
        help="Original uncompressed phone map SQLite file for recorded-way verification",
    )
    parser.add_argument(
        "--travel-packed-manifest",
        type=Path,
        action="append",
        default=[],
        help="Packed phone map manifest beside its installed context and geometry files",
    )
    parser.add_argument("--area", type=area, action="append", required=True)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument(
        "--candidate-images-file",
        type=Path,
        help="Private Panoramax picture IDs to recheck before writing city files",
    )
    args = parser.parse_args()
    if args.road_azimuth_fallback and (
        args.osm_road_graph is None or args.output is None
    ):
        parser.error("--road-azimuth-fallback requires --osm-road-graph and --output")
    if not args.rays and not args.private_panoramax_rays:
        parser.error("at least one ray input is required")
    panorama_report = None
    if args.panoramax_bridge_report is not None:
        if len(args.private_panoramax_rays) != 1 or args.rays or args.output is None:
            parser.error(
                "sequence bridging requires one private Panoramax snapshot and --output"
            )
        panorama_report = [
            json.loads(line)
            for line in read_private(
                args.panoramax_bridge_report, 64 * 1024**2
            ).splitlines()
            if line.strip()
        ]
        snapshot = json.loads(
            read_private(args.private_panoramax_rays[0], 64 * 1024**2)
        )
        if not panorama_report or panorama_report[0] != snapshot.get("corpus_metadata"):
            parser.error(
                "the original Panoramax report must match the private ray snapshot"
            )
    rows, provisional = load_batches(args.rays)
    if args.private_panoramax_rays:
        if args.confirmed_rays or args.candidate_images_file:
            parser.error(
                "owner-review Panoramax inputs are only for private city drafts"
            )
        if provisional or any(row.get("source") != "mobile" for row in rows):
            parser.error(
                "combine owner-review Panoramax inputs with eligible mobile rays"
            )
        private_rows, _ = load_batches(
            args.private_panoramax_rays, private_panoramax=True
        )
        rows.extend(private_rows)
        if len(rows) > 50_000:
            parser.error("choose a smaller area for batches above 50000 rays")
    if args.candidate_images_file is not None:
        images = pan_candidate_images(rows, args.boundaries, set(dict(args.area)))
        fd = os.open(
            args.candidate_images_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(images, handle)
            handle.write("\n")
        print(json.dumps({"panoramax_candidate_images": len(images)}))
        return
    if args.id_key_file is None:
        parser.error("--id-key-file is required for city drafts")
    has_travel_bundles = args.travel_bundle or args.travel_packed_manifest
    if has_travel_bundles and not args.osm_road_graph:
        parser.error("travel bundles require --osm-road-graph")
    confirmed = None
    if args.confirmed_rays is not None:
        confirmed, unchecked_confirmation = load_batches(args.confirmed_rays)
        if unchecked_confirmation:
            parser.error("--confirmed-rays cannot contain provisional Panoramax inputs")
    elif provisional:
        parser.error(
            "provisional Panoramax rays require --confirmed-rays for city drafts"
        )
    panels = (
        json.loads(read_private(args.panel_evidence, 8 * 1024**2))
        if args.panel_evidence
        else []
    )
    if not isinstance(panels, list):
        parser.error("panel evidence must be a JSON array")
    previous = (
        load_identities(
            json.loads(read_private(args.previous_identities, 64 * 1024**2))
        )
        if args.previous_identities
        else ()
    )
    totals = write_city_drafts(
        rows,
        args.boundaries,
        args.area,
        args.output,
        read_private(args.id_key_file, 4096),
        confirmed=confirmed,
        roads=RoadHeadingIndex.load(args.osm_road_graph)
        if args.osm_road_graph
        else None,
        panel_evidence=panels,
        travel_bundles=TravelBundles(args.travel_bundle, args.travel_packed_manifest)
        if has_travel_bundles
        else None,
        private_panoramax=bool(args.private_panoramax_rays),
        previous_identities=previous,
        road_azimuth_fallback=args.road_azimuth_fallback,
        panoramax_report=panorama_report,
    )
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()

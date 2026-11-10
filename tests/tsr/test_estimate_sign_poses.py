import json
import math
from dataclasses import replace

from fiona.transform import transform
import pytest

from scripts.tsr.collection.estimate_sign_poses import (
    METRIC,
    WGS84,
    angle,
    consolidate_sequences,
    delta_angle,
    estimate,
    image_bearing_candidate,
    project,
    subtract,
    vector,
)
from scripts.tsr.collection.run_sign_pose_batch import (
    load_batches,
    pan_candidate_images,
    write_city_drafts,
)
from scripts.tsr.collection.sign_identities import identity_entry, match_identities


TARGET, _ = project([8.43], [48.90])[0]


def simulated_rays(
    viewpoints, *, start=0, target=TARGET, code="DE:274-30", group=None, headings=None
):
    records = []
    for index, heading in enumerate(viewpoints, start):
        dx, dy = vector(heading)
        radius = 28.0 + index % 4
        position = (target[0] + dx * radius, target[1] + dy * radius)
        [lon], [lat] = transform(METRIC, WGS84, [position[0]], [position[1]])
        _, rotation = project([lon], [lat])[0]
        raw = {
            "source": "mobile" if index % 2 else "panoramax",
            "observation_id": f"sighting-{index}",
            "image_id": f"image-{index}",
            "sequence_id": "survey",
            "sign_code": code,
            "longitude": lon,
            "latitude": lat,
            "bearing_degrees": (angle(subtract(target, position)) - rotation) % 360,
            "bearing_error_deg": 0.15,
            "horizontal_error_m": 0.10,
            "pose_basis": "calibrated",
            "captured_at": f"2026-11-10T08:00:{index:02}Z",
        }
        if group is not None:
            raw.update(source="mobile", group_id=group)
        if headings is not None:
            # One-metre face normal pointing at headings in the metric frame.
            apparent = abs(math.cos(math.radians(delta_angle(heading, headings))))
            raw["angular_width_deg"] = math.degrees(
                2 * math.atan(apparent / (2 * radius))
            )
            raw["width_relative_error"] = 0.10
        records.append(raw)
    return records


def test_mixed_sources_recover_position_and_north_wrapping_front_heading():
    rows = simulated_rays([284, 321, 358, 31, 72])
    [(code, fit, heading)], _ = estimate(rows)
    assert code == "DE:274-30"
    assert math.dist(fit.point, TARGET) < 0.01
    assert fit.radius < 1.0
    assert {ray.source for ray in fit.rays} == {"mobile", "panoramax"}
    assert delta_angle(heading[0], 358) < 3
    assert heading[1] < 25
    assert heading[2] == "front_visibility"


def test_foreshortening_can_constrain_heading_when_visibility_alone_cannot():
    viewpoints = [10, 30, 46, 65, 82]
    [(_, _, wide)], _ = estimate(simulated_rays(viewpoints))
    assert wide[1] > 45 and wide[2] == "front_visibility"
    [(_, _, heading)], _ = estimate(simulated_rays(viewpoints, headings=30))
    assert delta_angle(heading[0], 30) < 12
    assert heading[1] < 45
    assert heading[2] == "panel_foreshortening"


def test_repeated_fix_and_near_parallel_inputs_cannot_manufacture_a_sign():
    rows = simulated_rays([0, 2, 4], group="sighting")
    assert estimate(rows)[0] == []
    rows = simulated_rays([290, 340, 55], group="sighting")
    rows[1]["fix_id"] = rows[2]["fix_id"] = "same-fix"
    assert estimate(rows)[0] == []


def test_nearby_opposite_facing_same_class_signs_stay_separate():
    south = (TARGET[0] + 18, TARGET[1] - 30)
    north_rays = simulated_rays([285, 315, 350, 40, 72])
    south_rays = simulated_rays([105, 140, 175, 220, 250], start=5, target=south)
    results, _ = estimate(north_rays + south_rays)
    assert len(results) == 2
    for expected, direction in ((TARGET, 0), (south, 180)):
        _, fit, heading = min(
            results, key=lambda row: math.dist(row[1].point, expected)
        )
        assert math.dist(fit.point, expected) < 0.01
        assert delta_angle(heading[0], direction) < 15


def test_opposite_faces_at_the_same_position_keep_distinct_identities():
    north = simulated_rays([315, 350, 20, 50], group="north")
    south = simulated_rays([135, 170, 200, 230], start=10, group="south")
    for row in north:
        row["sequence_id"] = "north"
    for row in south:
        row["sequence_id"] = "south"
    estimated, _ = estimate(north + south)
    results = consolidate_sequences(estimated)
    assert len(results) == 2
    assert all(math.dist(fit.point, TARGET) < 0.01 for _, fit, _ in results)
    assert delta_angle(results[0][2][0], results[1][2][0]) > 175


def test_close_same_class_and_direction_fit_refits_distinct_sequences():
    north = simulated_rays([305, 338, 20], group="first")
    next_pass = simulated_rays([312, 352, 30], start=10, group="second")
    for row in next_pass:
        row["sequence_id"] = "next-pass"
    [first], _ = estimate(north)
    [second], _ = estimate(next_pass)
    [(code, fit, _)] = consolidate_sequences([first, second])
    assert code == first[0]
    assert math.dist(fit.point, TARGET) < 0.01
    assert len(fit.rays) == 6

    at_limit = replace(second[1], point=(first[1].point[0] + 20, first[1].point[1]))
    assert len(consolidate_sequences([first, (code, at_limit, second[2])])) == 2
    assert len(consolidate_sequences([first, ("DE:274-50", second[1], second[2])])) == 2

    third_rows = simulated_rays([312, 352, 30], start=20, group="third")
    for row in third_rows:
        row["sequence_id"] = "third-pass"
    [third], _ = estimate(third_rows)

    def offset(fit, metres):
        return replace(fit, point=(first[1].point[0] + metres, first[1].point[1]))

    chain = [
        first,
        (code, offset(second[1], 12), second[2]),
        (code, offset(third[1], 24), third[2]),
    ]
    assert len(consolidate_sequences(chain)) == 3


def test_private_identity_ledger_reuses_an_unambiguous_sign_across_new_sightings():
    [first], _ = estimate(simulated_rays([305, 338, 20], group="first"))
    [second], _ = estimate(simulated_rays([312, 352, 30], start=10, group="second"))
    secret = b"k" * 32
    old = identity_entry(first[0], first[1], secret)
    new = identity_entry(second[0], second[1], secret)
    assert new["id"] != old["id"]
    assert not set(old["evidence"]).intersection(new["evidence"])
    match_identities([new], [old])
    assert new["id"] == old["id"]
    other = identity_entry(second[0], second[1], secret)
    other["view_direction"] = (old["view_direction"] + 180) % 360
    match_identities([other], [old])
    assert other["id"] != old["id"]


def test_private_panoramax_batches_cannot_enter_the_public_confirmation_path(tmp_path):
    path = tmp_path / "private.json"
    document = {
        "private_panoramax_review": True,
        "origin_rechecked": False,
        "rays": simulated_rays([10]),
    }
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="--private-panoramax-rays"):
        load_batches([path])
    assert load_batches([path], private_panoramax=True) == (document["rays"], False)
    document["rays"][0]["source"] = "mobile"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="only Panoramax"):
        load_batches([path], private_panoramax=True)
    path.write_text(
        json.dumps([simulated_rays([10])[0] | {"picture_visibility": "owner-only"}])
    )
    with pytest.raises(ValueError, match="restricted Panoramax"):
        load_batches([path])


def test_crop_less_sighting_adds_only_an_assumed_center_ray():
    rows = simulated_rays([305, 338, 20], group="sighting")
    rows[0].update(evidence_kind="sighting", pose_basis="assumed")
    [(_, fit, _)], _ = estimate(rows)
    [sighting] = [ray for ray in fit.rays if ray.evidence_kind == "sighting"]
    assert sighting.solver_row(fit.point)["source_kind"] == "qualified_live_sighting"
    rows[0]["angular_width_deg"] = 1
    with pytest.raises(ValueError, match="assumed camera model"):
        estimate(rows)


def test_city_draft_filters_position_and_contains_no_private_ray_ids(tmp_path):
    coordinates = [
        [8.42, 48.89],
        [8.44, 48.89],
        [8.44, 48.91],
        [8.42, 48.91],
        [8.42, 48.89],
    ]
    polygon = tmp_path / "boundary.geojson"
    polygon.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"kind": "gemeinde_ags", "id": "08231000"},
                        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
                    }
                ],
            }
        )
    )
    output = tmp_path / "draft"
    rows = simulated_rays([285, 310, 358, 35, 73])
    uncertain = simulated_rays([20], start=10, group="mobile")[0]
    uncertain["horizontal_error_m"] = 51
    totals = write_city_drafts(
        [*rows, uncertain],
        polygon,
        [("08231000", "pforzheim"), ("08235033", "bad-herrenalb")],
        output,
        b"k" * 32,
    )
    assert totals["municipalities"] == {
        "08231000": {"position_estimates": 1, "heading_estimates": 1},
        "08235033": {"position_estimates": 0, "heading_estimates": 0},
    }
    assert (
        totals["fit_diagnostics"]["mobile_rays_withheld_for_position_uncertainty"] == 1
    )
    content = (output / "pforzheim.geojson").read_text()
    assert not {"sighting-0", "image-0", "survey"}.intersection(content.split('"'))
    [feature] = json.loads(content)["features"]
    assert feature["properties"]["source_types"] == "mobile,panoramax"
    assert feature["properties"]["sighting_count"] == 5
    assert feature["properties"]["position_status"] == "estimated"
    assert feature["properties"]["azimut"] is not None
    start, end = feature["properties"]["front_azimuth_arc_deg"]
    assert start > end  # The north-facing interval wraps across zero.
    assert (output / "pforzheim.geojson").stat().st_mode & 0o077 == 0
    assert pan_candidate_images(rows, polygon, {"08231000"}) == [
        "image-0",
        "image-2",
        "image-4",
    ]

    altered = [*rows[:-1], rows[-1] | {"bearing_error_deg": 0.2}]
    blocked = write_city_drafts(
        rows,
        polygon,
        [("08231000", "pforzheim")],
        tmp_path / "blocked",
        b"k" * 32,
        confirmed=altered,
    )
    assert blocked["municipalities"]["08231000"]["position_estimates"] == 0
    assert blocked["fit_diagnostics"]["fits_with_unconfirmed_source"] == 1


def test_image_bearing_proxy_balances_repeated_sequences_at_north():
    from types import SimpleNamespace

    rays = [
        SimpleNamespace(
            bearing=(facing + 180) % 360,
            image=f"image-{i}",
            fix=f"fix-{i}",
            sequence=sequence,
            position=(i * 3, 0),
            position_error=1,
            angular_error=18,
            key=str(i),
        )
        for i, (facing, sequence) in enumerate([(340, "A")] * 5 + [(20, "B")])
    ]
    proxy = image_bearing_candidate(rays)
    assert delta_angle(proxy.heading, 0) < 0.01
    assert proxy.views == 6 and proxy.sequences == 2
    assert proxy.bearing_allowance == 18
    rays[-1].bearing = 340
    assert image_bearing_candidate(rays) is None

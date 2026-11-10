"""Private azimuth sensitivity estimates from verified rectangular panel corners."""

from __future__ import annotations

from itertools import product
import math

import numpy as np

from scripts.tsr.collection.estimate_sign_poses import (
    angle_envelope,
    delta_angle,
    number,
)


def camera_normal(corners, width, height, fov, aspect):
    focal = width / (2 * math.tan(math.radians(fov / 2)))
    frame = [(-aspect, -1), (aspect, -1), (aspect, 1), (-aspect, 1)]
    equations, values = [], []
    for (x, y), (u, v) in zip(frame, corners):
        u, v = (u - width / 2) / focal, (v - height / 2) / focal
        equations.extend(
            ((x, y, 1, 0, 0, 0, -u * x, -u * y), (0, 0, 0, x, y, 1, -v * x, -v * y))
        )
        values.extend((u, v))
    try:
        h = np.append(np.linalg.solve(equations, values), 1).reshape(3, 3)
    except np.linalg.LinAlgError:
        return None
    a, b, translation = h.T
    length_a, length_b = np.linalg.norm(a), np.linalg.norm(b)
    if (
        min(length_a, length_b) <= 0
        or abs(length_a / length_b - 1) > 0.18
        or abs(a @ b) > 0.18 * length_a * length_b
    ):
        return None
    normal = np.cross(a, b)
    normal /= np.linalg.norm(normal)
    if normal @ translation > 0:
        normal = -normal
    return normal


def quad_heading(record):
    """Compute a front-normal envelope under declared lens and pose assumptions."""
    width = number(record["image_width"], 1, 20_000)
    height = number(record["image_height"], 1, 20_000)
    fov = number(record["horizontal_fov_deg"], 25, 115)
    fov_error = number(record["fov_allowance_deg"], 0, 15)
    yaw = number(record["camera_yaw_deg"], 0, 360)
    yaw_error = number(record["yaw_allowance_deg"], 0, 45)
    tilt = number(record["tilt_allowance_deg"], 0, 20)
    error = number(record["corner_allowance_px"], 0, 10)
    aspect = number(record.get("panel_aspect_ratio", 1), 0.2, 5)
    corners = record["corners_xy"]
    if len(corners) != 4 or any(
        len(p) != 2
        or not (error < p[0] < width - error and error < p[1] < height - error)
        for p in corners
    ):
        return None
    edges = [np.subtract(b, a) for a, b in zip(corners, corners[1:] + corners[:1])]
    if min(np.linalg.norm(edge) for edge in edges) < 32:
        return None
    if any(
        a[0] * b[1] - a[1] * b[0] <= 0 for a, b in zip(edges, edges[1:] + edges[:1])
    ):
        return None
    nominal = camera_normal(corners, width, height, fov, aspect)
    if nominal is None:
        return None
    heading = (yaw + math.degrees(math.atan2(nominal[0], nominal[2]))) % 360
    deviations = []
    focal_samples = sorted({fov - fov_error, fov, fov + fov_error})
    for dx_dy in (
        [(0,) * 8, *product((-error, error), repeat=8)] if error else [(0,) * 8]
    ):
        shifted = [
            (x + dx_dy[2 * i], y + dx_dy[2 * i + 1]) for i, (x, y) in enumerate(corners)
        ]
        for angle in focal_samples:
            normal = camera_normal(shifted, width, height, angle, aspect)
            if normal is None:
                continue
            horizontal = math.hypot(normal[0], normal[2])
            if horizontal < 0.5:
                return None
            tilted = math.degrees(math.asin(math.sin(math.radians(tilt)) / horizontal))
            direction = yaw + math.degrees(math.atan2(normal[0], normal[2]))
            deviations.append(delta_angle(direction, heading) + tilted + yaw_error)
    if not deviations or max(deviations) >= 90:
        return None
    return heading, max(deviations)


def panel_heading(records):
    """Combine confirmed views of one panel without averaging away yaw allowance."""
    if len({record["image_id"] for record in records}) != len(records):
        raise ValueError("duplicate panel image")
    evidence = [
        result for record in records if (result := quad_heading(record)) is not None
    ]
    if len(evidence) < 2:
        return None
    headings = [
        h
        for h in range(360)
        if all(
            delta_angle(h, facing) <= allowance + 0.5 for facing, allowance in evidence
        )
    ]
    interval = angle_envelope(headings, padding=1)
    if interval is None:
        return None
    return {
        "azimut_deg": interval[0],
        "sensitivity_half_width_deg": interval[1],
        "views": len(evidence),
        "method": "rectangular_panel_homography",
    }

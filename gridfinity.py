"""
Ultra Light Gridfinity Bin generator — manifold3d port of
UltraLightGridfinityBins.scad by HuMa_Meng (CC BY-NC-SA 4.0).

This is a faithful 1:1 mapping of the SCAD source to manifold3d primitives.
The key correspondence:

  SCAD                                    →   manifold3d
  ----------------------------------------------------------------
  cube([w,d,h])                          →   Manifold.cube([w,d,h])
  cylinder(h, r_bot, r_top)              →   Manifold.cylinder(h, rb, rt, n)
  translate([x,y,z]) X                   →   X.translate([x,y,z])
  mirror([1,0,0]) X                      →   X.mirror([1,0,0])
  union() { A B C }                      →   A + B + C
  difference() { A B C }                 →   A - B - C
  hull() { A B C D }                     →   Manifold.batch_hull([A,B,C,D])

Geometry is identical to OpenSCAD's, modulo cylinder discretization (set by
``CIRCULAR_SEGMENTS``).  CSG runs in C++ via manifold3d ⇒ a full bin generates
in single-digit milliseconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import manifold3d as m
import numpy as np


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

LabelPosition = Literal["Full", "Left", "Center", "Right"]


@dataclass
class GridfinityParams:
    grids_x: float = 1.0
    grids_y: float = 2.0
    grids_z: float = 3.0

    half_grid_right: bool = True
    half_grid_top: bool = True
    half_grid_base: bool = False

    wall_thickness: float = 1.0
    ultra_light_base: bool = True
    ultra_light_labels: bool = True
    # Multiplier on the auto-computed rib count under ultra-light label tabs.
    # 1.0 = original SCAD behaviour (one rib every 13 mm). 2.0 = twice as many.
    label_support_density: float = 1.0

    magnets: bool = False
    magnet_diameter: float = 6.15
    magnet_depth: float = 2.2

    dividers: bool = False
    dividers_x: int = 0
    dividers_y: int = 1

    labels: bool = False
    label_for_each_section: bool = True
    label_position: LabelPosition = "Full"
    label_width: float = 30.0
    label_depth: float = 13.0

    scoops: bool = False
    scoop_radius: float = 15.0


# ---------------------------------------------------------------------------
# Constants from the SCAD source
# ---------------------------------------------------------------------------

OFFSET_XY = 0.25
BASIC_UNIT_XY = 42.0
BASIC_UNIT_Z = 7.0


def _unit_xy(p: "GridfinityParams") -> float:
    """Effective basic unit XY size.

    SCAD: ``Basic_Unit_XY = Half_Grid_Base ? 0.5 * 42.0 : 42.0;``
    With ``half_grid_base`` on, the count ``gx_/gy_`` is doubled and the unit
    halved → external size of the bin stays the same, but the base footprint
    is split into 4× more (smaller) feet.
    """
    return 0.5 * BASIC_UNIT_XY if p.half_grid_base else BASIC_UNIT_XY
BASIC_RADIUS_1 = 4.0
BASIC_RADIUS_2 = 8.0
TOP_CLEARANCE_OFFSET = 0.6
STACKING_LIP_WIDTH = 2.6
LABEL_HEIGHT = 1.0

# Discretization to mirror OpenSCAD's $fa / $fs adaptive scheme. Each cylinder
# gets segments = max(5, min(ceil(360/FA), ceil(2π·r / FS))).  These are the
# values from the SCAD source's "[Hidden] $fa = 8;  $fs = 0.25;" — so our
# triangulation should match OpenSCAD's bin output 1:1.
FA = 8.0
FS = 0.25
# Floor on segments: a circle never has fewer than this many segments
MIN_SEGMENTS = 5
# Used for the few circles that don't have an obvious radius (e.g. when we
# don't dispatch to _cyl). Kept as a fallback.
CIRCULAR_SEGMENTS = 32

import math as _math
def _segments_for_radius(r: float) -> int:
    """OpenSCAD-equivalent fragment count for a cylinder of given radius."""
    if r <= 1e-6:
        return MIN_SEGMENTS
    by_angle = _math.ceil(360.0 / FA)
    by_length = _math.ceil(2.0 * _math.pi * r / FS)
    return max(MIN_SEGMENTS, min(by_angle, by_length))


Manifold = m.Manifold


# ---------------------------------------------------------------------------
# SCAD-style primitive helpers (named identically to the OpenSCAD operators)
# ---------------------------------------------------------------------------

def _cyl(x: float, y: float, z: float, h: float, r_bot: float, r_top: float,
         segments: int = 0) -> Manifold:
    """SCAD's `translate([x,y,z]) cylinder(h, r_bot, r_top)`.

    Segment count follows OpenSCAD's $fa/$fs scheme based on the larger of the
    two radii — same as OpenSCAD itself.  Pass `segments=N` to override.
    """
    r_bot = max(r_bot, 1e-4)
    r_top = max(r_top, 1e-4)
    h = max(h, 1e-6)
    if segments <= 0:
        segments = _segments_for_radius(max(r_bot, r_top))
    return Manifold.cylinder(h, r_bot, r_top, circular_segments=segments).translate([x, y, z])


def _box(x0: float, y0: float, z0: float, w: float, d: float, h: float) -> Manifold:
    """SCAD's `translate([x0,y0,z0]) cube([w,d,h])`."""
    return Manifold.cube([w, d, h], center=False).translate([x0, y0, z0])


def _hull4(c0: Manifold, c1: Manifold, c2: Manifold, c3: Manifold) -> Manifold:
    """The omnipresent `hull() { 4 cylinders at corners }` pattern."""
    return Manifold.batch_hull([c0, c1, c2, c3])


# Tiny over-size for subtraction shapes to avoid coplanar-surface CSG
# robustness issues (manifold3d, like CGAL, leaves zero-thickness shells when
# two surfaces coincide exactly).  ε is far below mesh tolerance / printer
# precision, so the resulting STL is geometrically equivalent.
EPS_VOID = 1e-3


def _hull4_void(corners: list, z0: float, h: float, rb: float, rt: float,
                segments: int = 0) -> Manifold:
    """Like `_hull4(four cylinders at corners)`, but the resulting solid is
    grown by EPS_VOID radially and in Z so it cleanly carves through any
    coincident outer surface.  Use this *only* for voids in difference()."""
    cyls = [_cyl(cx, cy, z0 - EPS_VOID, h + 2 * EPS_VOID,
                 rb + EPS_VOID, rt + EPS_VOID, segments)
            for cx, cy in corners]
    return Manifold.batch_hull(cyls)


def _union_all(parts: list) -> Manifold:
    parts = [p for p in parts if p is not None and not p.is_empty()]
    if not parts:
        return Manifold()
    res = parts[0]
    for p in parts[1:]:
        res = res + p
    return res


def _diff_all(base: Manifold, voids: list) -> Manifold:
    voids = [v for v in voids if v is not None and not v.is_empty()]
    if not voids:
        return base
    res = base
    for v in voids:
        res = res - v
    return res


# ---------------------------------------------------------------------------
# Bin pieces — each function name and structure mirrors the SCAD module of
# the same purpose so it stays auditable side-by-side with the .scad file.
# ---------------------------------------------------------------------------


def _make_magnet_holes(p: GridfinityParams, sx: float, sy: float) -> Manifold:
    r = p.magnet_diameter / 2.0
    h = p.magnet_depth
    cyls = [
        _cyl(sx + BASIC_RADIUS_2,                  sy + BASIC_RADIUS_2,                  0, h, r, r),
        _cyl(sx + _unit_xy(p) - BASIC_RADIUS_2,  sy + BASIC_RADIUS_2,                  0, h, r, r),
        _cyl(sx + BASIC_RADIUS_2,                  sy + _unit_xy(p) - BASIC_RADIUS_2,  0, h, r, r),
        _cyl(sx + _unit_xy(p) - BASIC_RADIUS_2,  sy + _unit_xy(p) - BASIC_RADIUS_2,  0, h, r, r),
    ]
    return _union_all(cyls)


def _make_bin_base_single(p: GridfinityParams, sx: float, sy: float,
                          wx: float, wy: float) -> Manifold:
    """One Gridfinity foot unit (full / half / quarter sized)."""
    radius_0 = 1.05 - OFFSET_XY
    radius_1 = 1.85 - OFFSET_XY
    radius_2 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 0.80
    h1 = 1.80
    h2 = 2.15
    wall = p.wall_thickness
    Wx = wx * _unit_xy(p)
    Wy = wy * _unit_xy(p)
    R = BASIC_RADIUS_1
    corners = [
        (sx + R,         sy + R),
        (sx + Wx - R,    sy + R),
        (sx + R,         sy + Wy - R),
        (sx + Wx - R,    sy + Wy - R),
    ]

    outer = _box(sx, sy, 0.0, Wx, Wy, h0 + h1 + h2 + wall)

    voids: list[Manifold] = []
    if p.ultra_light_base:
        # Layer 1: bottom transition
        cyls = [_cyl(cx, cy, wall,
                     h0 - 0.5858 * wall,
                     radius_0 - 0.4142 * wall,
                     radius_1 - wall)
                for cx, cy in corners]
        voids.append(_hull4(*cyls))
        # Layer 2: vertical mid wall
        cyls = [_cyl(cx, cy, h0 + 0.4142 * wall, h1,
                     radius_1 - wall, radius_1 - wall)
                for cx, cy in corners]
        voids.append(_hull4(*cyls))
        # Layer 3: outward flare
        cyls = [_cyl(cx, cy, h0 + h1 + 0.4142 * wall, h2,
                     radius_1 - wall, radius_2 - wall)
                for cx, cy in corners]
        voids.append(_hull4(*cyls))
        # Layer 4: small inset under the lip
        cyls = [_cyl(cx, cy, h0 + h1 + h2, 0.4142 * wall,
                     radius_2 - 1.4142 * wall, radius_2 - wall)
                for cx, cy in corners]
        voids.append(_hull4(*cyls))
        # Layer 5: top chamfer (overlaps Layer 4 in z by design)
        cyls = [_cyl(cx, cy, h0 + h1 + h2, 1.4142 * wall,
                     radius_2 - 1.4142 * wall, radius_2)
                for cx, cy in corners]
        voids.append(_hull4(*cyls))

    if (not p.half_grid_base) and p.magnets and wx == 1.0 and wy == 1.0:
        voids.append(_make_magnet_holes(p, sx, sy))

    result = _diff_all(outer, voids)

    # Magnet ring reinforcement (4 cylinders around magnet holes), so the
    # walls around magnets stay at least wall_thickness even after the
    # ultra-light hollow chops the foot.
    if (not p.half_grid_base) and p.magnets and wx == 1.0 and wy == 1.0:
        ring_ro = (p.magnet_diameter / 2.0) + p.wall_thickness
        ring_h = p.magnet_depth + p.wall_thickness
        d = BASIC_RADIUS_2 - R
        ring_centers = [
            (sx + R + d,        sy + R + d),
            (sx + Wx - R - d,   sy + R + d),
            (sx + R + d,        sy + Wy - R - d),
            (sx + Wx - R - d,   sy + Wy - R - d),
        ]
        rings = _union_all([_cyl(cx, cy, 0, ring_h, ring_ro, ring_ro)
                            for cx, cy in ring_centers])
        rings = rings - _make_magnet_holes(p, sx, sy)
        result = result + rings

    return result


def _make_bin_base(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    """Tile foot units to cover the requested grid footprint."""
    parts: list[Manifold] = []
    fx = int(gx_)
    fy = int(gy_)
    half_x = (gx_ - fx) > 0
    half_y = (gy_ - fy) > 0

    for ix in range(fx):
        for iy in range(fy):
            parts.append(_make_bin_base_single(p, ix * _unit_xy(p), iy * _unit_xy(p), 1.0, 1.0))
    if half_x:
        for iy in range(fy):
            parts.append(_make_bin_base_single(p, fx * _unit_xy(p), iy * _unit_xy(p), 0.5, 1.0))
    if half_y:
        for ix in range(fx):
            parts.append(_make_bin_base_single(p, ix * _unit_xy(p), fy * _unit_xy(p), 1.0, 0.5))
    if half_x and half_y:
        parts.append(_make_bin_base_single(p, fx * _unit_xy(p), fy * _unit_xy(p), 0.5, 0.5))
    return _union_all(parts)


def _make_bin_body(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    """Outer rounded-rect tube of the bin."""
    radius_0 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 4.75
    h1 = 7.0 - h0
    h2 = (p.grids_z - 1) * BASIC_UNIT_Z
    Wx = gx_ * _unit_xy(p)
    Wy = gy_ * _unit_xy(p)
    R = BASIC_RADIUS_1
    corners = [
        (R,        R),
        (Wx - R,   R),
        (R,        Wy - R),
        (Wx - R,   Wy - R),
    ]

    outer_cyls = [_cyl(cx, cy, h0, h1 + h2, radius_0, radius_0) for cx, cy in corners]
    outer = _hull4(*outer_cyls)
    inner_r = radius_0 - p.wall_thickness
    inner_cyls = [_cyl(cx, cy, h0, h1 + h2, inner_r, inner_r) for cx, cy in corners]
    inner = _hull4(*inner_cyls)
    return outer - inner


def _make_bin_stacklip(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    """Stacking lip on top of the bin (interlock profile)."""
    radius_0 = 1.15
    radius_1 = 1.85
    radius_2 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = STACKING_LIP_WIDTH - p.wall_thickness
    h1 = 0.60
    h2 = 0.70
    h3 = 1.80
    h4 = 1.90
    h5 = 0.75
    h_start = (p.grids_z * BASIC_UNIT_Z) - (h0 + h1)

    Wx = gx_ * _unit_xy(p)
    Wy = gy_ * _unit_xy(p)
    R = BASIC_RADIUS_1
    corners = [
        (R,        R),
        (Wx - R,   R),
        (R,        Wy - R),
        (Wx - R,   Wy - R),
    ]

    def _ring(z0: float, h: float, rb: float, rt: float) -> Manifold:
        return _hull4(*[_cyl(cx, cy, z0, h, rb, rt) for cx, cy in corners])

    outer = _ring(h_start, h0 + h1 + h2 + h3 + h4, radius_2, radius_2)
    # Use _hull4_void for subtractions — needed because some voids have radii
    # that match radius_2 (outer) → coplanar surfaces would leave thin shells.
    voids = [
        _hull4_void(corners, h_start,                     h0, radius_2 - p.wall_thickness, radius_0),
        _hull4_void(corners, h_start + h0,                h1, radius_0, radius_0),
        _hull4_void(corners, h_start + h0 + h1,           h2, radius_0, radius_1),
        _hull4_void(corners, h_start + h0 + h1 + h2,      h3, radius_1, radius_1),
        _hull4_void(corners, h_start + h0 + h1 + h2 + h3, h4, radius_1, radius_2),
        _hull4_void(corners, h_start + h0 + h1 + h2 + h3 + h4 - h5, h5, radius_2, radius_2),
    ]
    return _diff_all(outer, voids)


def _make_bin_dividers(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    """Vertical dividers inside the bin."""
    if not p.dividers or (p.dividers_x <= 0 and p.dividers_y <= 0):
        return Manifold()
    radius_0 = 1.10
    Wx = gx_ * _unit_xy(p)
    Wy = gy_ * _unit_xy(p)
    wall = p.wall_thickness

    rsx = (Wx - 2 * OFFSET_XY - 2 * wall - 2 * radius_0
           - p.dividers_x * (wall + 2 * radius_0)) / (p.dividers_x + 1)
    rsy = (Wy - 2 * OFFSET_XY - 2 * wall - 2 * radius_0
           - p.dividers_y * (wall + 2 * radius_0)) / (p.dividers_y + 1)
    sxy = OFFSET_XY + wall + radius_0

    R = BASIC_RADIUS_1
    outer_r = BASIC_RADIUS_1 - OFFSET_XY
    z_h = (p.grids_z * BASIC_UNIT_Z) - TOP_CLEARANCE_OFFSET - p.wall_thickness
    outer_cyls = [
        _cyl(R,        R,        p.wall_thickness, z_h, outer_r, outer_r),
        _cyl(Wx - R,   R,        p.wall_thickness, z_h, outer_r, outer_r),
        _cyl(R,        Wy - R,   p.wall_thickness, z_h, outer_r, outer_r),
        _cyl(Wx - R,   Wy - R,   p.wall_thickness, z_h, outer_r, outer_r),
    ]
    outer = _hull4(*outer_cyls)

    full_h = p.grids_z * BASIC_UNIT_Z
    voids: list[Manifold] = []
    for dx in range(p.dividers_x + 1):
        for dy in range(p.dividers_y + 1):
            ox = dx * (rsx + 2 * radius_0 + wall)
            oy = dy * (rsy + 2 * radius_0 + wall)
            cell_corners = [
                (sxy + ox,        sxy + oy),
                (sxy + ox + rsx,  sxy + oy),
                (sxy + ox,        sxy + oy + rsy),
                (sxy + ox + rsx,  sxy + oy + rsy),
            ]
            cell_cyls = [_cyl(cx, cy, 0.0, full_h, radius_0, radius_0)
                         for cx, cy in cell_corners]
            voids.append(_hull4(*cell_cyls))
    return _diff_all(outer, voids)


def _make_bin_label(p: GridfinityParams, gx_: float, gy_: float,
                    start_x: float, start_y: float, width: float, depth: float) -> Manifold:
    """One label tap (slab + sloped triangular underside).

    Built as the SCAD `hull()` of two thin slabs — convex hull is exactly the
    quadrilateral wedge we want.
    """
    z_top = (p.grids_z * BASIC_UNIT_Z) - TOP_CLEARANCE_OFFSET

    # 1 mm top slab
    slab = _box(start_x, start_y - depth, z_top - LABEL_HEIGHT, width, depth, LABEL_HEIGHT)

    # Sloped wedge (hull of two thin rectangles, exactly mirroring SCAD)
    rect_a = _box(start_x, start_y - depth, z_top - LABEL_HEIGHT, width, depth, 0.0001)
    rect_b = _box(start_x, start_y, z_top - LABEL_HEIGHT - depth, width, 0.0001, 0.0001)
    triangle = Manifold.batch_hull([rect_a, rect_b])

    if p.ultra_light_labels:
        import math
        # SCAD's default "one rib every ~13 mm". Density multiplier shrinks
        # the spacing → more ribs per label tab.
        density = max(p.label_support_density, 0.1)
        rips_max_bridge = 13.0 / density
        wall = p.wall_thickness
        if p.label_position == "Full" and p.dividers:
            rips = math.ceil(
                (gx_ * _unit_xy(p) + p.dividers_x * wall - 2 * OFFSET_XY)
                / (rips_max_bridge * (p.dividers_x + 1))
            ) * (p.dividers_x + 1) - p.dividers_x
        else:
            rips = math.ceil(width / rips_max_bridge) + 1
        # Cap so ribs don't overlap (need at least 0.5 mm of gap between them).
        rips_max = max(2, int((width - 0.5) / max(wall, 0.1)))
        rips = max(2, min(rips, rips_max))
        rips_distance = (width - rips * wall) / (rips - 1)

        rip_voids = []
        for r in range(rips - 1):
            rx = start_x + wall + r * (rips_distance + wall)
            rip_voids.append(_box(rx, start_y - depth, z_top - LABEL_HEIGHT - depth,
                                  rips_distance, depth, depth))
        triangle = _diff_all(triangle, rip_voids)

    return slab + triangle


def _make_bin_labels(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    if not p.labels:
        return Manifold()

    dx_n = p.dividers_x if (p.dividers and p.label_for_each_section) else 0
    dy_n = p.dividers_y if (p.dividers and p.label_for_each_section) else 0
    Wx = gx_ * _unit_xy(p)
    Wy = gy_ * _unit_xy(p)
    wall = p.wall_thickness
    parts: list[Manifold] = []

    if p.label_position == "Full":
        for dy in range(dy_n + 1):
            label_w = Wx - 2 * OFFSET_XY
            label_d = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
            sy = (Wy * (dy_n + 1 - dy)
                  - OFFSET_XY * (dy_n + 1 - 2.0 * dy)
                  + wall * dy) / (dy_n + 1)
            parts.append(_make_bin_label(p, gx_, gy_, OFFSET_XY, sy, label_w, label_d))

    elif p.label_position == "Left":
        for dx in range(dx_n + 1):
            for dy in range(dy_n + 1):
                lw = (p.label_width + STACKING_LIP_WIDTH) if dx == 0 else p.label_width
                ld = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
                sx = OFFSET_XY + ((Wx - 2 * OFFSET_XY - wall) / (dx_n + 1)) * dx
                sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy
                parts.append(_make_bin_label(p, gx_, gy_, sx, sy, lw, ld))

    elif p.label_position == "Center":
        for dx in range(dx_n + 1):
            for dy in range(dy_n + 1):
                lw = p.label_width
                ld = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
                cell_w = (Wx - 2 * OFFSET_XY - wall) / (dx_n + 1)
                sx = OFFSET_XY + cell_w * dx + cell_w / 2.0 - lw / 2.0
                sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy
                parts.append(_make_bin_label(p, gx_, gy_, sx, sy, lw, ld))

    elif p.label_position == "Right":
        for dx in range(dx_n + 1):
            for dy in range(dy_n + 1):
                lw = (p.label_width + STACKING_LIP_WIDTH) if dx == dx_n else p.label_width
                ld = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
                cell_w = (Wx - 2 * OFFSET_XY - wall) / (dx_n + 1)
                sx = OFFSET_XY + cell_w * dx + (cell_w + wall) - lw
                sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy
                parts.append(_make_bin_label(p, gx_, gy_, sx, sy, lw, ld))

    return _union_all(parts)


def _make_scoop_one(p: GridfinityParams, gx_: float, gy_: float,
                    start_y: float, spacing: float) -> Manifold:
    Wx = gx_ * _unit_xy(p)
    wall = p.wall_thickness
    h0 = 0.6
    h1 = 0 if p.ultra_light_base else 4.75
    Sr = p.scoop_radius

    outer = _box(OFFSET_XY, start_y, wall,
                 Wx - 2 * OFFSET_XY, Sr + spacing,
                 (p.grids_z * BASIC_UNIT_Z) - wall - h0)

    cyl_y = start_y + Sr + spacing
    cyl_z = wall + Sr + h1
    cyl_len = Wx - 2 * OFFSET_XY
    # Cylinder along +X: build in standard +Z orientation, rotate 90° around Y.
    scoop_cyl = (Manifold.cylinder(cyl_len, Sr, Sr, circular_segments=_segments_for_radius(Sr))
                 .rotate([0, 90, 0])
                 .translate([OFFSET_XY, cyl_y, cyl_z]))
    above = _box(OFFSET_XY, start_y + spacing, wall + Sr + h1,
                 Wx - 2 * OFFSET_XY, 2 * Sr, p.grids_z * BASIC_UNIT_Z)
    return _diff_all(outer, [scoop_cyl, above])


def _make_bin_scoops(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    if not p.scoops or p.scoop_radius <= 0:
        return Manifold()
    dy_n = p.dividers_y if p.dividers else 0
    Wy = gy_ * _unit_xy(p)
    wall = p.wall_thickness
    parts: list[Manifold] = []
    for dy in range(dy_n + 1):
        spacing = STACKING_LIP_WIDTH if dy == 0 else wall
        sy = OFFSET_XY + ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy
        parts.append(_make_scoop_one(p, gx_, gy_, sy, spacing))
    return _union_all(parts)


def _make_bin_clean_single(p: GridfinityParams, sx: float, sy: float,
                           wx: float, wy: float) -> Manifold:
    radius_0 = 1.05 - OFFSET_XY
    radius_1 = 1.85 - OFFSET_XY
    radius_2 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 0.80
    h1 = 1.80
    h2 = 2.15
    Wx = wx * _unit_xy(p)
    Wy = wy * _unit_xy(p)
    R = BASIC_RADIUS_1
    corners = [
        (sx + R,         sy + R),
        (sx + Wx - R,    sy + R),
        (sx + R,         sy + Wy - R),
        (sx + Wx - R,    sy + Wy - R),
    ]

    outer = _box(sx, sy, 0.0, Wx, Wy, h0 + h1 + h2)
    voids = [
        _hull4(*[_cyl(cx, cy, 0.0,        h0, radius_0, radius_1) for cx, cy in corners]),
        _hull4(*[_cyl(cx, cy, h0,         h1, radius_1, radius_1) for cx, cy in corners]),
        _hull4(*[_cyl(cx, cy, h0 + h1,    h2, radius_1, radius_2) for cx, cy in corners]),
    ]
    res = _diff_all(outer, voids)

    if (not p.half_grid_base) and p.magnets and wx == 1.0 and wy == 1.0:
        res = res + _make_magnet_holes(p, sx, sy)
    return res


def _make_bin_clean(p: GridfinityParams, gx_: float, gy_: float) -> Manifold:
    """Subtraction volume that gives the bin its rounded outer profile.

    SCAD subtracts this from the union of base+body+lip+... at the end.
    """
    parts: list[Manifold] = []
    fx = int(gx_)
    fy = int(gy_)
    half_x = (gx_ - fx) > 0
    half_y = (gy_ - fy) > 0
    for ix in range(fx):
        for iy in range(fy):
            parts.append(_make_bin_clean_single(p, ix * _unit_xy(p), iy * _unit_xy(p), 1.0, 1.0))
    if half_x:
        for iy in range(fy):
            parts.append(_make_bin_clean_single(p, fx * _unit_xy(p), iy * _unit_xy(p), 0.5, 1.0))
    if half_y:
        for ix in range(fx):
            parts.append(_make_bin_clean_single(p, ix * _unit_xy(p), fy * _unit_xy(p), 1.0, 0.5))
    if half_x and half_y:
        parts.append(_make_bin_clean_single(p, fx * _unit_xy(p), fy * _unit_xy(p), 0.5, 0.5))
    base_clean = _union_all(parts)

    radius_0 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 4.40
    Wx = gx_ * _unit_xy(p)
    Wy = gy_ * _unit_xy(p)
    R = BASIC_RADIUS_1
    corners = [
        (R,        R),
        (Wx - R,   R),
        (R,        Wy - R),
        (Wx - R,   Wy - R),
    ]
    h_total = p.grids_z * BASIC_UNIT_Z + h0
    inner_cyls = [_cyl(cx, cy, 0.0, h_total, radius_0, radius_0) for cx, cy in corners]
    inner = _hull4(*inner_cyls)
    outer_box = _box(0, 0, 0, Wx, Wy, h_total)
    around = outer_box - inner

    below = _box(0, 0, -12.0, Wx, Wy, 12.0)

    return _union_all([base_clean, around, below])


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def _mirror_xy(part: Manifold, mirror_x: bool, mirror_y: bool,
               Wx: float, Wy: float) -> Manifold:
    if not mirror_x and not mirror_y:
        return part
    if mirror_x and not mirror_y:
        return part.mirror([1, 0, 0]).translate([Wx, 0, 0])
    if not mirror_x and mirror_y:
        return part.mirror([0, 1, 0]).translate([0, Wy, 0])
    return part.mirror([1, 0, 0]).mirror([0, 1, 0]).translate([Wx, Wy, 0])


def build_bin(p: GridfinityParams) -> Manifold:
    gx_ = 2.0 * p.grids_x if p.half_grid_base else p.grids_x
    gy_ = 2.0 * p.grids_y if p.half_grid_base else p.grids_y
    Wx = gx_ * _unit_xy(p)
    Wy = gy_ * _unit_xy(p)

    base = _make_bin_base(p, gx_, gy_)
    base = _mirror_xy(base, not p.half_grid_right, not p.half_grid_top, Wx, Wy)

    body = _make_bin_body(p, gx_, gy_)
    lip = _make_bin_stacklip(p, gx_, gy_)

    pieces = [base, body, lip]
    if p.dividers and (p.dividers_x > 0 or p.dividers_y > 0):
        pieces.append(_make_bin_dividers(p, gx_, gy_))
    if p.labels:
        pieces.append(_make_bin_labels(p, gx_, gy_))
    if p.scoops:
        pieces.append(_make_bin_scoops(p, gx_, gy_))
    union_part = _union_all(pieces)

    clean = _make_bin_clean(p, gx_, gy_)
    clean = _mirror_xy(clean, not p.half_grid_right, not p.half_grid_top, Wx, Wy)

    result = union_part - clean

    # SCAD centers the footprint on the origin
    return result.translate([-Wx / 2.0, -Wy / 2.0, 0])


def to_stl_bytes(part: Manifold) -> bytes:
    """Return the binary-STL bytes for a manifold."""
    mesh = part.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3].astype(np.float32)
    tris = np.asarray(mesh.tri_verts, dtype=np.uint32)

    # Build STL triangles + recompute face normals
    v0 = verts[tris[:, 0]]
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(n, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    n = (n / norms).astype(np.float32)

    n_tri = len(tris)
    out = bytearray()
    out += b"\x00" * 80                     # header
    out += int(n_tri).to_bytes(4, "little") # uint32 triangle count
    # Triangle records: 12B normal + 36B verts + 2B attribute
    record = np.zeros((n_tri, 50), dtype=np.uint8)
    # Pack as struct of 12 floats + 2 padding bytes per triangle
    tri_buf = np.zeros((n_tri, 12), dtype=np.float32)
    tri_buf[:, 0:3] = n
    tri_buf[:, 3:6] = v0
    tri_buf[:, 6:9] = v1
    tri_buf[:, 9:12] = v2
    record[:, :48] = tri_buf.view(np.uint8).reshape(n_tri, 48)
    out += record.tobytes()
    return bytes(out)


def export(p: GridfinityParams, path: str) -> None:
    part = build_bin(p)
    with open(path, "wb") as f:
        f.write(to_stl_bytes(part))


if __name__ == "__main__":
    import sys, time
    p = GridfinityParams()
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gridfinity_default.stl"
    t = time.perf_counter()
    export(p, out)
    print(f"Wrote {out} in {(time.perf_counter()-t)*1000:.0f}ms")

"""
Ultra Light Gridfinity Bin generator — Python/build123d port of
UltraLightGridfinityBins.scad by HuMa_Meng (CC BY-NC-SA 4.0).

Reproduces the geometry of the OpenSCAD source so STL output matches
what users would get from running OpenSCAD on the original file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from build123d import (
    Cylinder,
    Box,
    Plane,
    Location,
    Pos,
    Rot,
    RectangleRounded,
    Circle,
    Mode,
    Align,
    Part,
    Solid,
    extrude,
    loft,
    export_stl,
    Compound,
    BuildSketch,
    Polygon,
)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

LabelPosition = Literal["Full", "Left", "Center", "Right"]


@dataclass
class GridfinityParams:
    # General
    grids_x: float = 1.0
    grids_y: float = 2.0
    grids_z: float = 3.0

    # Half grid
    half_grid_right: bool = True
    half_grid_top: bool = True
    half_grid_base: bool = False

    # Ultra-light
    wall_thickness: float = 1.0
    ultra_light_base: bool = True
    ultra_light_labels: bool = True

    # Magnets
    magnets: bool = False
    magnet_diameter: float = 6.15
    magnet_depth: float = 2.2

    # Dividers
    dividers: bool = False
    dividers_x: int = 0
    dividers_y: int = 1

    # Labels
    labels: bool = False
    label_for_each_section: bool = True
    label_position: LabelPosition = "Full"
    label_width: float = 30.0
    label_depth: float = 13.0

    # Scoop
    scoops: bool = False
    scoop_radius: float = 15.0


# ---------------------------------------------------------------------------
# Constants from SCAD source
# ---------------------------------------------------------------------------

OFFSET_XY = 0.25
BASIC_UNIT_XY = 42.0
BASIC_UNIT_Z = 7.0
BASIC_RADIUS_1 = 4.0
BASIC_RADIUS_2 = 8.0
TOP_CLEARANCE_OFFSET = 0.6
STACKING_LIP_WIDTH = 2.6
LABEL_HEIGHT = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def rounded_rect_frustum(
    x0: float,
    y0: float,
    width_x: float,
    width_y: float,
    z0: float,
    height: float,
    r_bot: float,
    r_top: float,
) -> Part:
    """Build the convex hull of 4 cylinders at the corners of a rectangle.

    In the SCAD source this pattern is used everywhere via ``hull() { 4
    cylinders }``.  When all 4 cylinders share their bottom radius and their
    top radius, the hull is exactly a prism whose horizontal cross-section is
    a rectangle with rounded corners (rectangle's straight edges from the
    cylinder positions, corner radius from the cylinder radius).

    The arguments mirror the SCAD usage: ``(x0, y0)`` is the rectangle's
    bottom-left, ``width_x`` and ``width_y`` are the outer rectangle size
    (i.e. corners are at ``(x0+r, y0+r) ... (x0+W-r, y0+H-r)`` style — but we
    expose the *rectangle* dimensions here, since that's how it composes).
    """
    if height <= 0:
        return Part()

    cx = x0 + width_x / 2.0
    cy = y0 + width_y / 2.0

    # Both rounded-rects share the same outer rectangle; only corner radius
    # changes between bottom and top.
    if abs(r_bot - r_top) < 1e-9:
        face = RectangleRounded(width_x, width_y, radius=r_bot).face()
        face = Plane.XY.offset(z0) * face
        return extrude(face, amount=height)

    face_bot = RectangleRounded(width_x, width_y, radius=r_bot).face()
    face_bot = Plane.XY.offset(z0) * face_bot
    face_top = RectangleRounded(width_x, width_y, radius=r_top).face()
    face_top = Plane.XY.offset(z0 + height) * face_top
    return loft([face_bot, face_top])


def cyl(x: float, y: float, z: float, h: float, r_bot: float, r_top: float) -> Part:
    """Cylinder with possibly different bottom/top radius (= SCAD cylinder)."""
    if h <= 0:
        return Part()
    if abs(r_bot - r_top) < 1e-9:
        return Pos(x, y, z + h / 2.0) * Cylinder(r_bot, h)
    # Truncated cone via loft of two circles. Build123d's Cylinder doesn't
    # support different radii in 0.10, so use loft of two CircleArcs/Faces.
    from build123d import Circle  # local import to keep top tidy

    f_bot = (Plane.XY.offset(z)) * Circle(r_bot).face()
    f_top = (Plane.XY.offset(z + h)) * Circle(r_top).face()
    return loft([f_bot, f_top])


def box(x0: float, y0: float, z0: float, w: float, d: float, h: float) -> Part:
    """Axis-aligned box at corner (x0, y0, z0), size (w, d, h)."""
    return Pos(x0 + w / 2.0, y0 + d / 2.0, z0 + h / 2.0) * Box(w, d, h)


def _to_part(x):
    """Coerce build123d boolean op results (which may be ShapeList) into a
    single shape with .volume / .moved() / boolean ops still working."""
    if x is None:
        return Part()
    # Solid / Compound / Part already work
    if isinstance(x, (Solid, Compound, Part)):
        return x
    # ShapeList or other iterable of shapes
    try:
        items = list(x)
    except TypeError:
        return x
    if not items:
        return Part()
    if len(items) == 1:
        return items[0]
    return Compound(items)


def _union_all(parts: list) -> Part:
    """Boolean-union an arbitrary list of parts, dropping empty ones."""
    parts = [p for p in parts if p is not None and getattr(p, "volume", 0) > 1e-9]
    if not parts:
        return Part()
    if len(parts) == 1:
        return parts[0]
    res = parts[0]
    for p in parts[1:]:
        res = _to_part(res + p)
    return res


def _diff(a, b):
    """Boolean-difference, coercing the result back to a usable shape."""
    return _to_part(a - b)


# ---------------------------------------------------------------------------
# Bin pieces
# ---------------------------------------------------------------------------


def _make_magnet_holes(p: GridfinityParams, sx: float, sy: float) -> Part:
    """Magnet cylinder voids placed at the 4 inner corners of one base unit."""
    r = p.magnet_diameter / 2.0
    h = p.magnet_depth
    parts = []
    for cx, cy in (
        (sx + BASIC_RADIUS_2, sy + BASIC_RADIUS_2),
        (sx + BASIC_UNIT_XY - BASIC_RADIUS_2, sy + BASIC_RADIUS_2),
        (sx + BASIC_RADIUS_2, sy + BASIC_UNIT_XY - BASIC_RADIUS_2),
        (sx + BASIC_UNIT_XY - BASIC_RADIUS_2, sy + BASIC_UNIT_XY - BASIC_RADIUS_2),
    ):
        parts.append(cyl(cx, cy, 0.0, h, r, r))
    return _union_all(parts)


def _make_bin_base_single(
    p: GridfinityParams,
    start_x: float,
    start_y: float,
    width_x: float,
    width_y: float,
) -> Part:
    """One Gridfinity base unit (full / half / quarter sized)."""
    radius_0 = 1.05 - OFFSET_XY
    radius_1 = 1.85 - OFFSET_XY
    radius_2 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 0.80
    h1 = 1.80
    h2 = 2.15
    wall = p.wall_thickness

    Wx = width_x * BASIC_UNIT_XY
    Wy = width_y * BASIC_UNIT_XY

    # Outer block
    outer = box(start_x, start_y, 0.0, Wx, Wy, h0 + h1 + h2 + wall)

    # Inner hollows (all built relative to the same outer rectangle of corners)
    # rect_W, rect_H follow the spacing between the 4 corner cylinders, plus
    # corner radius * 2 to give the rounded-rect frustum the right outer size.
    # In SCAD the 4 cylinders are at corners (x0+R, y0+R) ... (x0+W-R, y0+W-R)
    # so the rounded-rect's outer extents go to (x0, y0) ... (x0+W, y0+W) when
    # corner radius == BASIC_RADIUS_1. For radii smaller than BASIC_RADIUS_1
    # the outer extents are (x0 + (R-r), y0 + (R-r)) ... (x0 + W - (R-r), ...).
    R = BASIC_RADIUS_1

    def _frustum_at(z0: float, h: float, rb: float, rt: float) -> Part:
        # Outer rectangle whose corners are inset by (R - max(rb, rt)) from the
        # block edges — but actually each level has its own size based on its
        # own radius.  Since loft expects the same outer rectangle on both
        # ends, we use the *cylinder centers* spacing plus radii.
        # Centers spacing in X: (Wx - 2R) ; in Y: (Wy - 2R).
        # Outer rect at the bottom: spacing + 2*rb (= Wx - 2R + 2*rb).
        # Outer rect at the top:    spacing + 2*rt (= Wx - 2R + 2*rt).
        # Loft requires same XY size on both faces — so we need a different
        # approach: build each level as a separate rounded-rect prism stack
        # since the outer rectangle changes when r changes.  But this is the
        # convex hull of cylinders, which in 3D produces sloped sides.
        #
        # Workaround: build the frustum as a loft between two rounded-rects
        # of *different* outer sizes — that *is* the convex hull when both
        # endpoints share centerline and the rectangle dimensions only differ
        # in their corner inflation.  build123d's loft will linearly interp.
        cx_spacing = Wx - 2 * R
        cy_spacing = Wy - 2 * R
        outer_w_bot = cx_spacing + 2 * rb
        outer_h_bot = cy_spacing + 2 * rb
        outer_w_top = cx_spacing + 2 * rt
        outer_h_top = cy_spacing + 2 * rt
        # Center of the rectangle
        cx = start_x + Wx / 2.0
        cy = start_y + Wy / 2.0
        f_bot = Pos(cx, cy, z0) * RectangleRounded(
            outer_w_bot, outer_h_bot, radius=rb
        ).face()
        f_top = Pos(cx, cy, z0 + h) * RectangleRounded(
            outer_w_top, outer_h_top, radius=rt
        ).face()
        return loft([f_bot, f_top])

    hollows: list[Part] = []
    if p.ultra_light_base:
        # Layer 1: from z=wall, height h0 - 0.5858*wall, radii r0-0.4142w → r1-w
        hollows.append(
            _frustum_at(
                wall,
                h0 - 0.5858 * wall,
                radius_0 - 0.4142 * wall,
                radius_1 - wall,
            )
        )
        # Layer 2: z=h0+0.4142w, height h1, radii r1-w both ends (prism)
        hollows.append(
            _frustum_at(h0 + 0.4142 * wall, h1, radius_1 - wall, radius_1 - wall)
        )
        # Layer 3: z=h0+h1+0.4142w, height h2, radii r1-w → r2-w
        hollows.append(
            _frustum_at(
                h0 + h1 + 0.4142 * wall,
                h2,
                radius_1 - wall,
                radius_2 - wall,
            )
        )
        # Layer 4: z=h0+h1+h2, height 0.4142w, radii r2-1.4142w → r2-w
        hollows.append(
            _frustum_at(
                h0 + h1 + h2,
                0.4142 * wall,
                radius_2 - 1.4142 * wall,
                radius_2 - wall,
            )
        )
        # Layer 5: z=h0+h1+h2, height 1.4142w, radii r2-1.4142w → r2 (overlaps
        # layer 4 by design — SCAD union())
        hollows.append(
            _frustum_at(
                h0 + h1 + h2,
                1.4142 * wall,
                radius_2 - 1.4142 * wall,
                radius_2,
            )
        )

    # Magnets are a *void* in the base block — handled together with hollows
    if (not p.half_grid_base) and p.magnets and width_x == 1.0 and width_y == 1.0:
        hollows.append(_make_magnet_holes(p, start_x, start_y))

    if hollows:
        result = _diff(outer, _union_all(hollows))
    else:
        result = outer

    # Magnet ring reinforcement — adds a thicker ring around the magnet hole
    # so it has wall_thickness around it even after the hollow chops the base.
    if (not p.half_grid_base) and p.magnets and width_x == 1.0 and width_y == 1.0:
        ring_r_outer = (p.magnet_diameter / 2.0) + p.wall_thickness
        ring_h = p.magnet_depth + p.wall_thickness
        # Place 4 cylinders, then subtract the magnet holes from them.
        c0 = (start_x + R + (BASIC_RADIUS_2 - R), start_y + R + (BASIC_RADIUS_2 - R))
        c1 = (start_x + Wx - R - (BASIC_RADIUS_2 - R), start_y + R + (BASIC_RADIUS_2 - R))
        c2 = (start_x + R + (BASIC_RADIUS_2 - R), start_y + Wy - R - (BASIC_RADIUS_2 - R))
        c3 = (start_x + Wx - R - (BASIC_RADIUS_2 - R), start_y + Wy - R - (BASIC_RADIUS_2 - R))
        rings = [cyl(cx, cy, 0.0, ring_h, ring_r_outer, ring_r_outer)
                 for (cx, cy) in (c0, c1, c2, c3)]
        ring_part = _diff(_union_all(rings), _make_magnet_holes(p, start_x, start_y))
        result = _union_all([result, ring_part])

    return result


def make_bin_base(p: GridfinityParams, gx_: float, gy_: float) -> Part:
    """Tile base units to cover the requested grid footprint."""
    parts: list[Part] = []
    full_x = int(gx_)
    full_y = int(gy_)
    half_x = (gx_ - full_x) > 0
    half_y = (gy_ - full_y) > 0

    for ix in range(full_x):
        for iy in range(full_y):
            parts.append(
                _make_bin_base_single(
                    p, ix * BASIC_UNIT_XY, iy * BASIC_UNIT_XY, 1.0, 1.0
                )
            )
    if half_x:
        for iy in range(full_y):
            parts.append(
                _make_bin_base_single(
                    p, full_x * BASIC_UNIT_XY, iy * BASIC_UNIT_XY, 0.5, 1.0
                )
            )
    if half_y:
        for ix in range(full_x):
            parts.append(
                _make_bin_base_single(
                    p, ix * BASIC_UNIT_XY, full_y * BASIC_UNIT_XY, 1.0, 0.5
                )
            )
    if half_x and half_y:
        parts.append(
            _make_bin_base_single(
                p,
                full_x * BASIC_UNIT_XY,
                full_y * BASIC_UNIT_XY,
                0.5,
                0.5,
            )
        )

    return _union_all(parts)


def make_bin_body(p: GridfinityParams, gx_: float, gy_: float) -> Part:
    """Outer rounded-rect tube of the bin (above the base)."""
    radius_0 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 4.75
    h1 = 7.0 - h0
    h2 = (p.grids_z - 1) * BASIC_UNIT_Z

    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY

    outer_w = Wx - 2 * BASIC_RADIUS_1 + 2 * radius_0
    outer_h = Wy - 2 * BASIC_RADIUS_1 + 2 * radius_0

    cx, cy = Wx / 2.0, Wy / 2.0
    profile_outer = Pos(cx, cy, h0) * RectangleRounded(
        outer_w, outer_h, radius=radius_0
    ).face()
    outer = extrude(profile_outer, amount=h1 + h2)

    inner_r = radius_0 - p.wall_thickness
    inner_w = Wx - 2 * BASIC_RADIUS_1 + 2 * inner_r
    inner_h = Wy - 2 * BASIC_RADIUS_1 + 2 * inner_r
    profile_inner = Pos(cx, cy, h0) * RectangleRounded(
        inner_w, inner_h, radius=inner_r
    ).face()
    inner = extrude(profile_inner, amount=h1 + h2)

    return _diff(outer, inner)


def make_bin_stacklip(p: GridfinityParams, gx_: float, gy_: float) -> Part:
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

    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY
    cx, cy = Wx / 2.0, Wy / 2.0
    R = BASIC_RADIUS_1

    def _ring(z0: float, h: float, rb: float, rt: float) -> Part:
        # Outer block goes by radius_2 throughout (spans the full lip)
        cx_spacing = Wx - 2 * R
        cy_spacing = Wy - 2 * R
        f_bot = Pos(cx, cy, z0) * RectangleRounded(
            cx_spacing + 2 * rb, cy_spacing + 2 * rb, radius=rb
        ).face()
        f_top = Pos(cx, cy, z0 + h) * RectangleRounded(
            cx_spacing + 2 * rt, cy_spacing + 2 * rt, radius=rt
        ).face()
        return loft([f_bot, f_top])

    outer_total_h = h0 + h1 + h2 + h3 + h4
    outer = _ring(h_start, outer_total_h, radius_2, radius_2)

    # Inner subtractions
    voids = []
    voids.append(_ring(h_start, h0, radius_2 - p.wall_thickness, radius_0))
    voids.append(_ring(h_start + h0, h1, radius_0, radius_0))
    voids.append(_ring(h_start + h0 + h1, h2, radius_0, radius_1))
    voids.append(_ring(h_start + h0 + h1 + h2, h3, radius_1, radius_1))
    voids.append(_ring(h_start + h0 + h1 + h2 + h3, h4, radius_1, radius_2))
    voids.append(
        _ring(h_start + h0 + h1 + h2 + h3 + h4 - h5, h5, radius_2, radius_2)
    )

    return _diff(outer, _union_all(voids))


def make_bin_dividers(p: GridfinityParams, gx_: float, gy_: float) -> Part:
    """Vertical dividers inside the bin."""
    if not p.dividers or (p.dividers_x <= 0 and p.dividers_y <= 0):
        return Part()
    radius_0 = 1.10
    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY
    R = BASIC_RADIUS_1
    wall = p.wall_thickness

    radius_spacing_x = (
        Wx - 2 * OFFSET_XY - 2 * wall - 2 * radius_0 - p.dividers_x * (wall + 2 * radius_0)
    ) / (p.dividers_x + 1)
    radius_spacing_y = (
        Wy - 2 * OFFSET_XY - 2 * wall - 2 * radius_0 - p.dividers_y * (wall + 2 * radius_0)
    ) / (p.dividers_y + 1)
    start_xy = OFFSET_XY + wall + radius_0

    # The "outer hull" is the bin interior up to (Grids_Z * 7 - clearance).
    # Loft of 4 cylinders r=BASIC_RADIUS_1-OFFSET_XY at corner positions, from
    # z=wall up to z=grids_z*7 - clearance.  This is just an extrusion of a
    # rounded rect (same radius top/bottom).
    outer_r = BASIC_RADIUS_1 - OFFSET_XY
    z0 = wall
    z_h = (p.grids_z * BASIC_UNIT_Z) - TOP_CLEARANCE_OFFSET - wall
    cx_spacing = Wx - 2 * R
    cy_spacing = Wy - 2 * R
    cx, cy = Wx / 2.0, Wy / 2.0
    outer_face = Pos(cx, cy, z0) * RectangleRounded(
        cx_spacing + 2 * outer_r, cy_spacing + 2 * outer_r, radius=outer_r
    ).face()
    outer = extrude(outer_face, amount=z_h)

    # Subtract divider sections — each is a rounded rect prism that fills a
    # cell, leaving wall_thickness wide separators.
    voids = []
    full_h = p.grids_z * BASIC_UNIT_Z
    for dx in range(p.dividers_x + 1):
        for dy in range(p.dividers_y + 1):
            # rounded rect with corner radius radius_0, dimensions
            # (radius_spacing_x + 2*r0) x (radius_spacing_y + 2*r0)
            cell_w = radius_spacing_x + 2 * radius_0
            cell_h = radius_spacing_y + 2 * radius_0
            ccx = (
                start_xy
                + dx * (radius_spacing_x + 2 * radius_0 + wall)
                + cell_w / 2.0
                - radius_0
            )
            ccy = (
                start_xy
                + dy * (radius_spacing_y + 2 * radius_0 + wall)
                + cell_h / 2.0
                - radius_0
            )
            face = Pos(ccx, ccy, 0.0) * RectangleRounded(
                cell_w, cell_h, radius=radius_0
            ).face()
            voids.append(extrude(face, amount=full_h))

    return _diff(outer, _union_all(voids))


def _make_bin_label(
    p: GridfinityParams,
    gx_: float,
    gy_: float,
    start_x: float,
    start_y: float,
    width: float,
    depth: float,
) -> Part:
    """One label tap (top slab + triangular rip below it)."""
    z_top = (p.grids_z * BASIC_UNIT_Z) - TOP_CLEARANCE_OFFSET

    # Top slab (the actual label surface, 1 mm thick)
    slab = box(start_x, start_y - depth, z_top - LABEL_HEIGHT, width, depth, LABEL_HEIGHT)

    # Triangular prism beneath the slab — equivalent to SCAD hull() of two
    # thin rectangles. Cross section in YZ at any X is a right triangle with
    # vertices:
    #   A = (start_y - depth, z_top - LH)        (top-back)
    #   B = (start_y,         z_top - LH)        (top-front)
    #   C = (start_y,         z_top - LH - depth)(bottom-front)
    with BuildSketch(Plane.YZ) as sk:
        Polygon(
            (start_y - depth, z_top - LABEL_HEIGHT),
            (start_y, z_top - LABEL_HEIGHT),
            (start_y, z_top - LABEL_HEIGHT - depth),
            align=None,
        )
    triangle = extrude(sk.sketch, amount=width)
    # Plane.YZ extrudes along +X. Move the prism to start_x.
    triangle = Pos(start_x, 0, 0) * triangle

    # Optional rip cutouts in the triangle (slab is left intact).
    if p.ultra_light_labels:
        rips_max_bridge = 13.0
        wall = p.wall_thickness
        import math
        if p.label_position == "Full" and p.dividers:
            rips = math.ceil(
                (gx_ * BASIC_UNIT_XY + p.dividers_x * wall - 2 * OFFSET_XY)
                / (rips_max_bridge * (p.dividers_x + 1))
            ) * (p.dividers_x + 1) - p.dividers_x
        else:
            rips = math.ceil(width / rips_max_bridge) + 1
        if rips < 2:
            rips = 2
        rips_distance = (width - rips * wall) / (rips - 1)

        rip_voids = []
        for r in range(rips - 1):
            rx = start_x + wall + r * (rips_distance + wall)
            rip_voids.append(
                box(rx, start_y - depth, z_top - LABEL_HEIGHT - depth,
                    rips_distance, depth, depth)
            )
        if rip_voids:
            triangle = _diff(triangle, _union_all(rip_voids))

    return _union_all([slab, triangle])


def make_bin_labels(p: GridfinityParams, gx_: float, gy_: float) -> Part:
    """All label taps for the bin."""
    if not p.labels:
        return Part()

    dividers_x = p.dividers_x if (p.dividers and p.label_for_each_section) else 0
    dividers_y = p.dividers_y if (p.dividers and p.label_for_each_section) else 0
    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY
    wall = p.wall_thickness
    parts: list[Part] = []

    if p.label_position == "Full":
        for dy in range(dividers_y + 1):
            label_w = Wx - 2 * OFFSET_XY
            label_d = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
            sy = (
                Wy * (dividers_y + 1 - dy)
                - OFFSET_XY * (dividers_y + 1 - 2.0 * dy)
                + wall * dy
            ) / (dividers_y + 1)
            parts.append(_make_bin_label(p, gx_, gy_, OFFSET_XY, sy, label_w, label_d))

    elif p.label_position == "Left":
        for dx in range(dividers_x + 1):
            for dy in range(dividers_y + 1):
                label_w = (p.label_width + STACKING_LIP_WIDTH) if dx == 0 else p.label_width
                label_d = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
                sx = OFFSET_XY + ((Wx - 2 * OFFSET_XY - wall) / (dividers_x + 1)) * dx
                sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dividers_y + 1)) * dy
                parts.append(_make_bin_label(p, gx_, gy_, sx, sy, label_w, label_d))

    elif p.label_position == "Center":
        for dx in range(dividers_x + 1):
            for dy in range(dividers_y + 1):
                label_w = p.label_width
                label_d = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
                cell_w = (Wx - 2 * OFFSET_XY - wall) / (dividers_x + 1)
                sx = OFFSET_XY + cell_w * dx + cell_w / 2.0 - label_w / 2.0
                sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dividers_y + 1)) * dy
                parts.append(_make_bin_label(p, gx_, gy_, sx, sy, label_w, label_d))

    elif p.label_position == "Right":
        for dx in range(dividers_x + 1):
            for dy in range(dividers_y + 1):
                label_w = (
                    (p.label_width + STACKING_LIP_WIDTH) if dx == dividers_x else p.label_width
                )
                label_d = (p.label_depth + STACKING_LIP_WIDTH) if dy == 0 else p.label_depth
                cell_w = (Wx - 2 * OFFSET_XY - wall) / (dividers_x + 1)
                sx = OFFSET_XY + cell_w * dx + (cell_w + wall) - label_w
                sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dividers_y + 1)) * dy
                parts.append(_make_bin_label(p, gx_, gy_, sx, sy, label_w, label_d))

    return _union_all(parts)


def _make_scoop_one(p: GridfinityParams, gx_: float, gy_: float, start_y: float, spacing: float) -> Part:
    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY
    wall = p.wall_thickness
    h0 = 0.6
    h1 = 0 if p.ultra_light_base else 4.75
    Sr = p.scoop_radius

    # Outer wedge: cube extending the scoop region
    outer = box(
        OFFSET_XY,
        start_y,
        wall,
        Wx - 2 * OFFSET_XY,
        Sr + spacing,
        (gy_ * BASIC_UNIT_Z) - wall - h0,  # SCAD: Grids_Z_ * Basic_Unit_Z, but Grids_Z_ == Grids_Z
    )
    # SCAD source uses Grids_Z_, which equals Grids_Z when not half_grid_base.
    # Recompute with the correct factor:
    outer = box(
        OFFSET_XY,
        start_y,
        wall,
        Wx - 2 * OFFSET_XY,
        Sr + spacing,
        (p.grids_z * BASIC_UNIT_Z) - wall - h0,
    )

    # Subtract a cylinder along X (the scoop curve)
    cx0 = OFFSET_XY  # SCAD translates to this X then rotates 90 around Y axis
    cyl_y = start_y + Sr + spacing
    cyl_z = wall + Sr + h1
    # Cylinder of radius Sr and length (Wx - 2*OFFSET_XY) along +X
    from build123d import Cylinder, Rot
    cyl_len = Wx - 2 * OFFSET_XY
    scoop_cyl = (
        Pos(cx0 + cyl_len / 2.0, cyl_y, cyl_z)
        * Rot(0, 90, 0)
        * Cylinder(Sr, cyl_len)
    )
    # And a box above the cylinder centerline (so the scoop opens upward)
    above = box(
        OFFSET_XY,
        start_y + spacing,
        wall + Sr + h1,
        Wx - 2 * OFFSET_XY,
        2 * Sr,
        p.grids_z * BASIC_UNIT_Z,
    )
    return _diff(outer, _union_all([scoop_cyl, above]))


def make_bin_scoops(p: GridfinityParams, gx_: float, gy_: float) -> Part:
    if not p.scoops or p.scoop_radius <= 0:
        return Part()
    dividers_y = p.dividers_y if p.dividers else 0
    Wy = gy_ * BASIC_UNIT_XY
    wall = p.wall_thickness
    parts: list[Part] = []
    for dy in range(dividers_y + 1):
        spacing = STACKING_LIP_WIDTH if dy == 0 else wall
        sy = OFFSET_XY + ((Wy - 2 * OFFSET_XY - wall) / (dividers_y + 1)) * dy
        parts.append(_make_scoop_one(p, gx_, gy_, sy, spacing))
    return _union_all(parts)


def _make_bin_clean_single(
    p: GridfinityParams,
    start_x: float,
    start_y: float,
    width_x: float,
    width_y: float,
) -> Part:
    """Per-base 'clean' subtraction shape — chamfers the foot profile."""
    radius_0 = 1.05 - OFFSET_XY
    radius_1 = 1.85 - OFFSET_XY
    radius_2 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 0.80
    h1 = 1.80
    h2 = 2.15
    Wx = width_x * BASIC_UNIT_XY
    Wy = width_y * BASIC_UNIT_XY
    R = BASIC_RADIUS_1
    cx, cy = start_x + Wx / 2.0, start_y + Wy / 2.0
    cx_spacing = Wx - 2 * R
    cy_spacing = Wy - 2 * R

    def _frustum(z0: float, h: float, rb: float, rt: float) -> Part:
        f_b = Pos(cx, cy, z0) * RectangleRounded(
            cx_spacing + 2 * rb, cy_spacing + 2 * rb, radius=rb
        ).face()
        f_t = Pos(cx, cy, z0 + h) * RectangleRounded(
            cx_spacing + 2 * rt, cy_spacing + 2 * rt, radius=rt
        ).face()
        return loft([f_b, f_t])

    outer = box(start_x, start_y, 0.0, Wx, Wy, h0 + h1 + h2)
    voids = [
        _frustum(0.0, h0, radius_0, radius_1),
        _frustum(h0, h1, radius_1, radius_1),
        _frustum(h0 + h1, h2, radius_1, radius_2),
    ]
    res = _diff(outer, _union_all(voids))

    if (not p.half_grid_base) and p.magnets and width_x == 1.0 and width_y == 1.0:
        res = _union_all([res, _make_magnet_holes(p, start_x, start_y)])
    return res


def make_bin_clean(p: GridfinityParams, gx_: float, gy_: float) -> Part:
    """Subtraction volume that gives the bin its rounded outer profile.

    SCAD subtracts this from the union of base+body+lip+... at the end.
    """
    parts: list[Part] = []
    full_x = int(gx_)
    full_y = int(gy_)
    half_x = (gx_ - full_x) > 0
    half_y = (gy_ - full_y) > 0
    for ix in range(full_x):
        for iy in range(full_y):
            parts.append(
                _make_bin_clean_single(
                    p, ix * BASIC_UNIT_XY, iy * BASIC_UNIT_XY, 1.0, 1.0
                )
            )
    if half_x:
        for iy in range(full_y):
            parts.append(
                _make_bin_clean_single(
                    p, full_x * BASIC_UNIT_XY, iy * BASIC_UNIT_XY, 0.5, 1.0
                )
            )
    if half_y:
        for ix in range(full_x):
            parts.append(
                _make_bin_clean_single(
                    p, ix * BASIC_UNIT_XY, full_y * BASIC_UNIT_XY, 1.0, 0.5
                )
            )
    if half_x and half_y:
        parts.append(
            _make_bin_clean_single(
                p,
                full_x * BASIC_UNIT_XY,
                full_y * BASIC_UNIT_XY,
                0.5,
                0.5,
            )
        )
    base_clean = _union_all(parts)

    # Outer "all-around" shape
    radius_0 = BASIC_RADIUS_1 - OFFSET_XY
    h0 = 4.40
    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY
    R = BASIC_RADIUS_1
    cx_spacing = Wx - 2 * R
    cy_spacing = Wy - 2 * R
    cx, cy = Wx / 2.0, Wy / 2.0
    outer_face = Pos(cx, cy, 0.0) * RectangleRounded(
        cx_spacing + 2 * radius_0, cy_spacing + 2 * radius_0, radius=radius_0
    ).face()
    outer_extrude = extrude(outer_face, amount=p.grids_z * BASIC_UNIT_Z + h0)
    outer_box = box(0, 0, 0, Wx, Wy, p.grids_z * BASIC_UNIT_Z + h0)
    around = _diff(outer_box, outer_extrude)

    below = box(0, 0, -12.0, Wx, Wy, 12.0)

    return _union_all([base_clean, around, below])


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def _mirror_xy(part: Part, mirror_x: bool, mirror_y: bool, Wx: float, Wy: float) -> Part:
    """Apply same mirroring transformations the SCAD source uses for half grids."""
    if not mirror_x and not mirror_y:
        return part
    from build123d import Plane, Pos as _Pos
    if mirror_x and not mirror_y:
        # translate([Wx,0,0]) mirror([1,0,0])
        part = part.mirror(Plane.YZ)
        part = _Pos(Wx, 0, 0) * part
        return part
    if not mirror_x and mirror_y:
        part = part.mirror(Plane.XZ)
        part = _Pos(0, Wy, 0) * part
        return part
    # both
    part = part.mirror(Plane.YZ).mirror(Plane.XZ)
    part = _Pos(Wx, Wy, 0) * part
    return part


def build_bin(p: GridfinityParams) -> Part:
    """Assemble the whole bin from its pieces."""
    gx_ = 2.0 * p.grids_x if p.half_grid_base else p.grids_x
    gy_ = 2.0 * p.grids_y if p.half_grid_base else p.grids_y

    Wx = gx_ * BASIC_UNIT_XY
    Wy = gy_ * BASIC_UNIT_XY

    base = make_bin_base(p, gx_, gy_)
    base = _mirror_xy(base, not p.half_grid_right, not p.half_grid_top, Wx, Wy)

    body = make_bin_body(p, gx_, gy_)
    lip = make_bin_stacklip(p, gx_, gy_)

    pieces = [base, body, lip]

    if p.dividers and (p.dividers_x > 0 or p.dividers_y > 0):
        pieces.append(make_bin_dividers(p, gx_, gy_))
    if p.labels:
        pieces.append(make_bin_labels(p, gx_, gy_))
    if p.scoops:
        pieces.append(make_bin_scoops(p, gx_, gy_))

    union_part = _union_all(pieces)

    clean = make_bin_clean(p, gx_, gy_)
    clean = _mirror_xy(clean, not p.half_grid_right, not p.half_grid_top, Wx, Wy)

    result = _diff(union_part, clean)

    # SCAD translates the whole thing so origin is centered on the footprint
    result = Pos(-Wx / 2.0, -Wy / 2.0, 0) * result
    return result


def export(p: GridfinityParams, path: str, tolerance: float = 0.1) -> None:
    """Generate the bin and export to STL."""
    part = build_bin(p)
    export_stl(part, path, tolerance=tolerance)


if __name__ == "__main__":
    # Smoke test
    import sys
    p = GridfinityParams()
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gridfinity_default.stl"
    export(p, out)
    print(f"Wrote {out}")

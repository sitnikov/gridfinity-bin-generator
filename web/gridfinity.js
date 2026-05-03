// 1:1 JavaScript port of gridfinity.py — uses manifold-3d (WASM).
//
// The function names, control flow, and constants mirror the Python source
// so they can be diffed line-by-line against the SCAD original.
//
// Caller bootstraps once:
//
//   import Module from 'https://unpkg.com/manifold-3d@3.4.1/manifold.js';
//   import { setManifold, buildBin } from './gridfinity.js';
//   const wasm = await Module(); wasm.setup();
//   setManifold(wasm.Manifold);
//   const bin = buildBin(params);

// ---------------------------------------------------------------------------
// Constants from the SCAD source (= gridfinity.py)
// ---------------------------------------------------------------------------

export const OFFSET_XY = 0.25;
export const BASIC_UNIT_XY = 42.0;
export const BASIC_UNIT_Z = 7.0;
export const BASIC_RADIUS_1 = 4.0;
export const BASIC_RADIUS_2 = 8.0;
export const TOP_CLEARANCE_OFFSET = 0.6;
export const STACKING_LIP_WIDTH = 2.6;
export const LABEL_HEIGHT = 1.0;

// Adaptive cylinder discretization (OpenSCAD $fa / $fs from the original
// SCAD's [Hidden] section).
export const FA = 8.0;
export const FS = 0.25;
export const MIN_SEGMENTS = 5;
export const CIRCULAR_SEGMENTS = 32;  // fallback only

// Tiny over-size for subtraction shapes to dodge coplanar-surface CSG breakage.
export const EPS_VOID = 1e-3;

// ---------------------------------------------------------------------------
// Default parameters — mirrors GridfinityParams dataclass.
// ---------------------------------------------------------------------------

export const DEFAULT_PARAMS = {
  grids_x: 1.0,
  grids_y: 2.0,
  grids_z: 3.0,

  half_grid_right: true,
  half_grid_top: true,
  half_grid_base: false,

  wall_thickness: 1.0,
  ultra_light_base: true,
  ultra_light_labels: true,
  label_support_density: 1.0,

  magnets: false,
  magnet_diameter: 6.15,
  magnet_depth: 2.2,

  dividers: false,
  dividers_x: 0,
  dividers_y: 1,

  labels: false,
  label_for_each_section: true,
  label_position: 'Full',
  label_width: 30.0,
  label_depth: 13.0,

  scoops: false,
  scoop_radius: 15.0,
};

// ---------------------------------------------------------------------------
// Module-scoped Manifold class (set once after WASM is initialised).
// ---------------------------------------------------------------------------

let Manifold = null;
export function setManifold(M) { Manifold = M; }

function _segments_for_radius(r) {
  if (r <= 1e-6) return MIN_SEGMENTS;
  const by_angle = Math.ceil(360.0 / FA);
  const by_length = Math.ceil(2.0 * Math.PI * r / FS);
  return Math.max(MIN_SEGMENTS, Math.min(by_angle, by_length));
}

function _unit_xy(p) {
  return p.half_grid_base ? 0.5 * BASIC_UNIT_XY : BASIC_UNIT_XY;
}

// ---------------------------------------------------------------------------
// SCAD-style primitive helpers
// ---------------------------------------------------------------------------

function _cyl(x, y, z, h, r_bot, r_top, segments = 0) {
  r_bot = Math.max(r_bot, 1e-4);
  r_top = Math.max(r_top, 1e-4);
  h = Math.max(h, 1e-6);
  if (segments <= 0) segments = _segments_for_radius(Math.max(r_bot, r_top));
  return Manifold.cylinder(h, r_bot, r_top, segments).translate([x, y, z]);
}

function _box(x0, y0, z0, w, d, h) {
  return Manifold.cube([w, d, h], false).translate([x0, y0, z0]);
}

function _hull4(c0, c1, c2, c3) {
  return Manifold.hull([c0, c1, c2, c3]);
}

function _hull4_void(corners, z0, h, rb, rt, segments = 0) {
  const cyls = corners.map(([cx, cy]) =>
    _cyl(cx, cy, z0 - EPS_VOID, h + 2 * EPS_VOID,
         rb + EPS_VOID, rt + EPS_VOID, segments));
  return Manifold.hull(cyls);
}

function _union_all(parts) {
  const filtered = parts.filter(p => p && !p.isEmpty());
  if (filtered.length === 0) return new Manifold();      // empty
  if (filtered.length === 1) return filtered[0];
  return Manifold.union(filtered);
}

function _diff_all(base, voids) {
  const filtered = voids.filter(v => v && !v.isEmpty());
  if (filtered.length === 0) return base;
  return Manifold.difference([base, ...filtered]);
}

// ---------------------------------------------------------------------------
// Bin pieces — names mirror the SCAD modules and Python functions.
// ---------------------------------------------------------------------------

function _make_magnet_holes(p, sx, sy) {
  const r = p.magnet_diameter / 2.0;
  const h = p.magnet_depth;
  const u = _unit_xy(p);
  return _union_all([
    _cyl(sx + BASIC_RADIUS_2,         sy + BASIC_RADIUS_2,         0, h, r, r),
    _cyl(sx + u - BASIC_RADIUS_2,     sy + BASIC_RADIUS_2,         0, h, r, r),
    _cyl(sx + BASIC_RADIUS_2,         sy + u - BASIC_RADIUS_2,     0, h, r, r),
    _cyl(sx + u - BASIC_RADIUS_2,     sy + u - BASIC_RADIUS_2,     0, h, r, r),
  ]);
}

function _make_bin_base_single(p, sx, sy, wx, wy) {
  const radius_0 = 1.05 - OFFSET_XY;
  const radius_1 = 1.85 - OFFSET_XY;
  const radius_2 = BASIC_RADIUS_1 - OFFSET_XY;
  const h0 = 0.80, h1 = 1.80, h2 = 2.15;
  const wall = p.wall_thickness;
  const u = _unit_xy(p);
  const Wx = wx * u, Wy = wy * u;
  const R = BASIC_RADIUS_1;
  const corners = [
    [sx + R,         sy + R],
    [sx + Wx - R,    sy + R],
    [sx + R,         sy + Wy - R],
    [sx + Wx - R,    sy + Wy - R],
  ];

  const outer = _box(sx, sy, 0.0, Wx, Wy, h0 + h1 + h2 + wall);

  const voids = [];
  if (p.ultra_light_base) {
    // Layer 1: bottom transition
    voids.push(_hull4(...corners.map(([cx, cy]) =>
      _cyl(cx, cy, wall,
           h0 - 0.5858 * wall,
           radius_0 - 0.4142 * wall,
           radius_1 - wall))));
    // Layer 2: vertical mid wall
    voids.push(_hull4(...corners.map(([cx, cy]) =>
      _cyl(cx, cy, h0 + 0.4142 * wall, h1,
           radius_1 - wall, radius_1 - wall))));
    // Layer 3: outward flare
    voids.push(_hull4(...corners.map(([cx, cy]) =>
      _cyl(cx, cy, h0 + h1 + 0.4142 * wall, h2,
           radius_1 - wall, radius_2 - wall))));
    // Layer 4: small inset under the lip
    voids.push(_hull4(...corners.map(([cx, cy]) =>
      _cyl(cx, cy, h0 + h1 + h2, 0.4142 * wall,
           radius_2 - 1.4142 * wall, radius_2 - wall))));
    // Layer 5: top chamfer (overlaps Layer 4 in z by design)
    voids.push(_hull4(...corners.map(([cx, cy]) =>
      _cyl(cx, cy, h0 + h1 + h2, 1.4142 * wall,
           radius_2 - 1.4142 * wall, radius_2))));
  }

  if (!p.half_grid_base && p.magnets && wx === 1.0 && wy === 1.0) {
    voids.push(_make_magnet_holes(p, sx, sy));
  }

  let result = _diff_all(outer, voids);

  if (!p.half_grid_base && p.magnets && wx === 1.0 && wy === 1.0) {
    const ring_ro = (p.magnet_diameter / 2.0) + p.wall_thickness;
    const ring_h = p.magnet_depth + p.wall_thickness;
    const d = BASIC_RADIUS_2 - R;
    const ring_centers = [
      [sx + R + d,        sy + R + d],
      [sx + Wx - R - d,   sy + R + d],
      [sx + R + d,        sy + Wy - R - d],
      [sx + Wx - R - d,   sy + Wy - R - d],
    ];
    let rings = _union_all(ring_centers.map(([cx, cy]) =>
      _cyl(cx, cy, 0, ring_h, ring_ro, ring_ro)));
    rings = rings.subtract(_make_magnet_holes(p, sx, sy));
    result = result.add(rings);
  }

  return result;
}

function _make_bin_base(p, gx_, gy_) {
  const u = _unit_xy(p);
  const parts = [];
  const fx = Math.trunc(gx_), fy = Math.trunc(gy_);
  const half_x = (gx_ - fx) > 0;
  const half_y = (gy_ - fy) > 0;

  for (let ix = 0; ix < fx; ix++) {
    for (let iy = 0; iy < fy; iy++) {
      parts.push(_make_bin_base_single(p, ix * u, iy * u, 1.0, 1.0));
    }
  }
  if (half_x) {
    for (let iy = 0; iy < fy; iy++) {
      parts.push(_make_bin_base_single(p, fx * u, iy * u, 0.5, 1.0));
    }
  }
  if (half_y) {
    for (let ix = 0; ix < fx; ix++) {
      parts.push(_make_bin_base_single(p, ix * u, fy * u, 1.0, 0.5));
    }
  }
  if (half_x && half_y) {
    parts.push(_make_bin_base_single(p, fx * u, fy * u, 0.5, 0.5));
  }
  return _union_all(parts);
}

function _make_bin_body(p, gx_, gy_) {
  const radius_0 = BASIC_RADIUS_1 - OFFSET_XY;
  const h0 = 4.75;
  const h1 = 7.0 - h0;
  const h2 = (p.grids_z - 1) * BASIC_UNIT_Z;
  const u = _unit_xy(p);
  const Wx = gx_ * u, Wy = gy_ * u;
  const R = BASIC_RADIUS_1;
  const corners = [
    [R, R],
    [Wx - R, R],
    [R, Wy - R],
    [Wx - R, Wy - R],
  ];
  const outer = _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, h0, h1 + h2, radius_0, radius_0)));
  const inner_r = radius_0 - p.wall_thickness;
  const inner = _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, h0, h1 + h2, inner_r, inner_r)));
  return outer.subtract(inner);
}

function _make_bin_stacklip(p, gx_, gy_) {
  const radius_0 = 1.15;
  const radius_1 = 1.85;
  const radius_2 = BASIC_RADIUS_1 - OFFSET_XY;
  const h0 = STACKING_LIP_WIDTH - p.wall_thickness;
  const h1 = 0.60, h2 = 0.70, h3 = 1.80, h4 = 1.90, h5 = 0.75;
  const h_start = (p.grids_z * BASIC_UNIT_Z) - (h0 + h1);
  const u = _unit_xy(p);
  const Wx = gx_ * u, Wy = gy_ * u;
  const R = BASIC_RADIUS_1;
  const corners = [
    [R, R],
    [Wx - R, R],
    [R, Wy - R],
    [Wx - R, Wy - R],
  ];
  const ring = (z0, h, rb, rt) =>
    _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, z0, h, rb, rt)));

  const outer = ring(h_start, h0 + h1 + h2 + h3 + h4, radius_2, radius_2);
  // _hull4_void for subtractions — voids share radii with outer (coplanar risk).
  const voids = [
    _hull4_void(corners, h_start,                     h0, radius_2 - p.wall_thickness, radius_0),
    _hull4_void(corners, h_start + h0,                h1, radius_0, radius_0),
    _hull4_void(corners, h_start + h0 + h1,           h2, radius_0, radius_1),
    _hull4_void(corners, h_start + h0 + h1 + h2,      h3, radius_1, radius_1),
    _hull4_void(corners, h_start + h0 + h1 + h2 + h3, h4, radius_1, radius_2),
    _hull4_void(corners, h_start + h0 + h1 + h2 + h3 + h4 - h5, h5, radius_2, radius_2),
  ];
  return _diff_all(outer, voids);
}

function _make_bin_dividers(p, gx_, gy_) {
  if (!p.dividers || (p.dividers_x <= 0 && p.dividers_y <= 0)) {
    return new Manifold();
  }
  const radius_0 = 1.10;
  const u = _unit_xy(p);
  const Wx = gx_ * u, Wy = gy_ * u;
  const wall = p.wall_thickness;
  const rsx = (Wx - 2 * OFFSET_XY - 2 * wall - 2 * radius_0
               - p.dividers_x * (wall + 2 * radius_0)) / (p.dividers_x + 1);
  const rsy = (Wy - 2 * OFFSET_XY - 2 * wall - 2 * radius_0
               - p.dividers_y * (wall + 2 * radius_0)) / (p.dividers_y + 1);
  const sxy = OFFSET_XY + wall + radius_0;

  const R = BASIC_RADIUS_1;
  const outer_r = BASIC_RADIUS_1 - OFFSET_XY;
  const z_h = (p.grids_z * BASIC_UNIT_Z) - TOP_CLEARANCE_OFFSET - p.wall_thickness;
  const outer = _hull4(
    _cyl(R,        R,        p.wall_thickness, z_h, outer_r, outer_r),
    _cyl(Wx - R,   R,        p.wall_thickness, z_h, outer_r, outer_r),
    _cyl(R,        Wy - R,   p.wall_thickness, z_h, outer_r, outer_r),
    _cyl(Wx - R,   Wy - R,   p.wall_thickness, z_h, outer_r, outer_r),
  );

  const full_h = p.grids_z * BASIC_UNIT_Z;
  const voids = [];
  for (let dx = 0; dx <= p.dividers_x; dx++) {
    for (let dy = 0; dy <= p.dividers_y; dy++) {
      const ox = dx * (rsx + 2 * radius_0 + wall);
      const oy = dy * (rsy + 2 * radius_0 + wall);
      const cell_corners = [
        [sxy + ox,        sxy + oy],
        [sxy + ox + rsx,  sxy + oy],
        [sxy + ox,        sxy + oy + rsy],
        [sxy + ox + rsx,  sxy + oy + rsy],
      ];
      voids.push(_hull4(...cell_corners.map(([cx, cy]) =>
        _cyl(cx, cy, 0.0, full_h, radius_0, radius_0))));
    }
  }
  return _diff_all(outer, voids);
}

function _make_bin_label(p, gx_, gy_, start_x, start_y, width, depth) {
  const z_top = (p.grids_z * BASIC_UNIT_Z) - TOP_CLEARANCE_OFFSET;

  // 1 mm top slab
  const slab = _box(start_x, start_y - depth, z_top - LABEL_HEIGHT, width, depth, LABEL_HEIGHT);

  // Sloped wedge (hull of two thin rectangles, mirroring SCAD)
  const rect_a = _box(start_x, start_y - depth, z_top - LABEL_HEIGHT, width, depth, 0.0001);
  const rect_b = _box(start_x, start_y, z_top - LABEL_HEIGHT - depth, width, 0.0001, 0.0001);
  let triangle = Manifold.hull([rect_a, rect_b]);

  if (p.ultra_light_labels) {
    const density = Math.max(p.label_support_density, 0.1);
    const rips_max_bridge = 13.0 / density;
    const wall = p.wall_thickness;
    const u = _unit_xy(p);
    let rips;
    if (p.label_position === 'Full' && p.dividers) {
      rips = Math.ceil(
        (gx_ * u + p.dividers_x * wall - 2 * OFFSET_XY)
        / (rips_max_bridge * (p.dividers_x + 1))
      ) * (p.dividers_x + 1) - p.dividers_x;
    } else {
      rips = Math.ceil(width / rips_max_bridge) + 1;
    }
    const rips_max = Math.max(2, Math.trunc((width - 0.5) / Math.max(wall, 0.1)));
    rips = Math.max(2, Math.min(rips, rips_max));
    const rips_distance = (width - rips * wall) / (rips - 1);

    const rip_voids = [];
    for (let r = 0; r < rips - 1; r++) {
      const rx = start_x + wall + r * (rips_distance + wall);
      rip_voids.push(_box(rx, start_y - depth, z_top - LABEL_HEIGHT - depth,
                          rips_distance, depth, depth));
    }
    triangle = _diff_all(triangle, rip_voids);
  }
  return slab.add(triangle);
}

function _make_bin_labels(p, gx_, gy_) {
  if (!p.labels) return new Manifold();
  const dx_n = (p.dividers && p.label_for_each_section) ? p.dividers_x : 0;
  const dy_n = (p.dividers && p.label_for_each_section) ? p.dividers_y : 0;
  const u = _unit_xy(p);
  const Wx = gx_ * u, Wy = gy_ * u;
  const wall = p.wall_thickness;
  const parts = [];

  if (p.label_position === 'Full') {
    for (let dy = 0; dy <= dy_n; dy++) {
      const label_w = Wx - 2 * OFFSET_XY;
      const label_d = (dy === 0) ? (p.label_depth + STACKING_LIP_WIDTH) : p.label_depth;
      const sy = (Wy * (dy_n + 1 - dy)
                  - OFFSET_XY * (dy_n + 1 - 2.0 * dy)
                  + wall * dy) / (dy_n + 1);
      parts.push(_make_bin_label(p, gx_, gy_, OFFSET_XY, sy, label_w, label_d));
    }
  } else if (p.label_position === 'Left') {
    for (let dx = 0; dx <= dx_n; dx++) {
      for (let dy = 0; dy <= dy_n; dy++) {
        const lw = (dx === 0) ? (p.label_width + STACKING_LIP_WIDTH) : p.label_width;
        const ld = (dy === 0) ? (p.label_depth + STACKING_LIP_WIDTH) : p.label_depth;
        const sx = OFFSET_XY + ((Wx - 2 * OFFSET_XY - wall) / (dx_n + 1)) * dx;
        const sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy;
        parts.push(_make_bin_label(p, gx_, gy_, sx, sy, lw, ld));
      }
    }
  } else if (p.label_position === 'Center') {
    for (let dx = 0; dx <= dx_n; dx++) {
      for (let dy = 0; dy <= dy_n; dy++) {
        const lw = p.label_width;
        const ld = (dy === 0) ? (p.label_depth + STACKING_LIP_WIDTH) : p.label_depth;
        const cell_w = (Wx - 2 * OFFSET_XY - wall) / (dx_n + 1);
        const sx = OFFSET_XY + cell_w * dx + cell_w / 2.0 - lw / 2.0;
        const sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy;
        parts.push(_make_bin_label(p, gx_, gy_, sx, sy, lw, ld));
      }
    }
  } else if (p.label_position === 'Right') {
    for (let dx = 0; dx <= dx_n; dx++) {
      for (let dy = 0; dy <= dy_n; dy++) {
        const lw = (dx === dx_n) ? (p.label_width + STACKING_LIP_WIDTH) : p.label_width;
        const ld = (dy === 0) ? (p.label_depth + STACKING_LIP_WIDTH) : p.label_depth;
        const cell_w = (Wx - 2 * OFFSET_XY - wall) / (dx_n + 1);
        const sx = OFFSET_XY + cell_w * dx + (cell_w + wall) - lw;
        const sy = (Wy - OFFSET_XY) - ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy;
        parts.push(_make_bin_label(p, gx_, gy_, sx, sy, lw, ld));
      }
    }
  }
  return _union_all(parts);
}

function _make_scoop_one(p, gx_, gy_, start_y, spacing) {
  const u = _unit_xy(p);
  const Wx = gx_ * u;
  const wall = p.wall_thickness;
  const h0 = 0.6;
  const h1 = p.ultra_light_base ? 0 : 4.75;
  const Sr = p.scoop_radius;

  const outer = _box(OFFSET_XY, start_y, wall,
                     Wx - 2 * OFFSET_XY, Sr + spacing,
                     (p.grids_z * BASIC_UNIT_Z) - wall - h0);

  const cyl_y = start_y + Sr + spacing;
  const cyl_z = wall + Sr + h1;
  const cyl_len = Wx - 2 * OFFSET_XY;
  // Cylinder along +X: build standing in +Z, rotate 90° around Y.
  const scoop_cyl = Manifold.cylinder(cyl_len, Sr, Sr, _segments_for_radius(Sr))
    .rotate([0, 90, 0])
    .translate([OFFSET_XY, cyl_y, cyl_z]);
  const above = _box(OFFSET_XY, start_y + spacing, wall + Sr + h1,
                     Wx - 2 * OFFSET_XY, 2 * Sr, p.grids_z * BASIC_UNIT_Z);
  return _diff_all(outer, [scoop_cyl, above]);
}

function _make_bin_scoops(p, gx_, gy_) {
  if (!p.scoops || p.scoop_radius <= 0) return new Manifold();
  const dy_n = p.dividers ? p.dividers_y : 0;
  const u = _unit_xy(p);
  const Wy = gy_ * u;
  const wall = p.wall_thickness;
  const parts = [];
  for (let dy = 0; dy <= dy_n; dy++) {
    const spacing = (dy === 0) ? STACKING_LIP_WIDTH : wall;
    const sy = OFFSET_XY + ((Wy - 2 * OFFSET_XY - wall) / (dy_n + 1)) * dy;
    parts.push(_make_scoop_one(p, gx_, gy_, sy, spacing));
  }
  return _union_all(parts);
}

function _make_bin_clean_single(p, sx, sy, wx, wy) {
  const radius_0 = 1.05 - OFFSET_XY;
  const radius_1 = 1.85 - OFFSET_XY;
  const radius_2 = BASIC_RADIUS_1 - OFFSET_XY;
  const h0 = 0.80, h1 = 1.80, h2 = 2.15;
  const u = _unit_xy(p);
  const Wx = wx * u, Wy = wy * u;
  const R = BASIC_RADIUS_1;
  const corners = [
    [sx + R,         sy + R],
    [sx + Wx - R,    sy + R],
    [sx + R,         sy + Wy - R],
    [sx + Wx - R,    sy + Wy - R],
  ];
  const outer = _box(sx, sy, 0.0, Wx, Wy, h0 + h1 + h2);
  const voids = [
    _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, 0.0,        h0, radius_0, radius_1))),
    _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, h0,         h1, radius_1, radius_1))),
    _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, h0 + h1,    h2, radius_1, radius_2))),
  ];
  let res = _diff_all(outer, voids);
  if (!p.half_grid_base && p.magnets && wx === 1.0 && wy === 1.0) {
    res = res.add(_make_magnet_holes(p, sx, sy));
  }
  return res;
}

function _make_bin_clean(p, gx_, gy_) {
  const u = _unit_xy(p);
  const parts = [];
  const fx = Math.trunc(gx_), fy = Math.trunc(gy_);
  const half_x = (gx_ - fx) > 0;
  const half_y = (gy_ - fy) > 0;
  for (let ix = 0; ix < fx; ix++) {
    for (let iy = 0; iy < fy; iy++) {
      parts.push(_make_bin_clean_single(p, ix * u, iy * u, 1.0, 1.0));
    }
  }
  if (half_x) {
    for (let iy = 0; iy < fy; iy++) {
      parts.push(_make_bin_clean_single(p, fx * u, iy * u, 0.5, 1.0));
    }
  }
  if (half_y) {
    for (let ix = 0; ix < fx; ix++) {
      parts.push(_make_bin_clean_single(p, ix * u, fy * u, 1.0, 0.5));
    }
  }
  if (half_x && half_y) {
    parts.push(_make_bin_clean_single(p, fx * u, fy * u, 0.5, 0.5));
  }
  const base_clean = _union_all(parts);

  const radius_0 = BASIC_RADIUS_1 - OFFSET_XY;
  const h0 = 4.40;
  const Wx = gx_ * u, Wy = gy_ * u;
  const R = BASIC_RADIUS_1;
  const corners = [
    [R,        R],
    [Wx - R,   R],
    [R,        Wy - R],
    [Wx - R,   Wy - R],
  ];
  const h_total = p.grids_z * BASIC_UNIT_Z + h0;
  const inner = _hull4(...corners.map(([cx, cy]) => _cyl(cx, cy, 0.0, h_total, radius_0, radius_0)));
  const outer_box = _box(0, 0, 0, Wx, Wy, h_total);
  const around = outer_box.subtract(inner);

  const below = _box(0, 0, -12.0, Wx, Wy, 12.0);

  return _union_all([base_clean, around, below]);
}

// ---------------------------------------------------------------------------
// Top level
// ---------------------------------------------------------------------------

function _mirror_xy(part, mirror_x, mirror_y, Wx, Wy) {
  if (!mirror_x && !mirror_y) return part;
  if (mirror_x && !mirror_y) return part.mirror([1, 0, 0]).translate([Wx, 0, 0]);
  if (!mirror_x && mirror_y) return part.mirror([0, 1, 0]).translate([0, Wy, 0]);
  return part.mirror([1, 0, 0]).mirror([0, 1, 0]).translate([Wx, Wy, 0]);
}

export function buildBin(params) {
  if (!Manifold) throw new Error('Manifold not initialised — call setManifold() first');
  const p = { ...DEFAULT_PARAMS, ...params };
  const u = _unit_xy(p);
  const gx_ = p.half_grid_base ? 2.0 * p.grids_x : p.grids_x;
  const gy_ = p.half_grid_base ? 2.0 * p.grids_y : p.grids_y;
  const Wx = gx_ * u;
  const Wy = gy_ * u;

  let base = _make_bin_base(p, gx_, gy_);
  base = _mirror_xy(base, !p.half_grid_right, !p.half_grid_top, Wx, Wy);

  const body = _make_bin_body(p, gx_, gy_);
  const lip = _make_bin_stacklip(p, gx_, gy_);

  const pieces = [base, body, lip];
  if (p.dividers && (p.dividers_x > 0 || p.dividers_y > 0)) {
    pieces.push(_make_bin_dividers(p, gx_, gy_));
  }
  if (p.labels)  pieces.push(_make_bin_labels(p, gx_, gy_));
  if (p.scoops)  pieces.push(_make_bin_scoops(p, gx_, gy_));
  const union_part = _union_all(pieces);

  let clean = _make_bin_clean(p, gx_, gy_);
  clean = _mirror_xy(clean, !p.half_grid_right, !p.half_grid_top, Wx, Wy);

  const result = union_part.subtract(clean);

  // SCAD centers the footprint on the origin
  return result.translate([-Wx / 2.0, -Wy / 2.0, 0]);
}

// ---------------------------------------------------------------------------
// Binary STL writer — same wire-format as Python's to_stl_bytes.
// ---------------------------------------------------------------------------

export function toStlBytes(part) {
  const mesh = part.getMesh();
  const numProp = mesh.numProp;
  const verts = mesh.vertProperties;
  const tris = mesh.triVerts;
  const nTri = tris.length / 3;

  // STL: 80-byte header + uint32 triangle count + nTri × 50-byte records
  // (each record = 12 floats + 2 attribute bytes).
  const buf = new ArrayBuffer(80 + 4 + nTri * 50);
  const dv = new DataView(buf);
  dv.setUint32(80, nTri, true);

  let pos = 84;
  for (let i = 0; i < nTri; i++) {
    const i0 = tris[i * 3]     * numProp;
    const i1 = tris[i * 3 + 1] * numProp;
    const i2 = tris[i * 3 + 2] * numProp;
    const x0 = verts[i0],     y0 = verts[i0 + 1], z0 = verts[i0 + 2];
    const x1 = verts[i1],     y1 = verts[i1 + 1], z1 = verts[i1 + 2];
    const x2 = verts[i2],     y2 = verts[i2 + 1], z2 = verts[i2 + 2];
    const ux = x1 - x0, uy = y1 - y0, uz = z1 - z0;
    const vx = x2 - x0, vy = y2 - y0, vz = z2 - z0;
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz) || 1.0;
    dv.setFloat32(pos, nx / len, true); pos += 4;
    dv.setFloat32(pos, ny / len, true); pos += 4;
    dv.setFloat32(pos, nz / len, true); pos += 4;
    dv.setFloat32(pos, x0, true);       pos += 4;
    dv.setFloat32(pos, y0, true);       pos += 4;
    dv.setFloat32(pos, z0, true);       pos += 4;
    dv.setFloat32(pos, x1, true);       pos += 4;
    dv.setFloat32(pos, y1, true);       pos += 4;
    dv.setFloat32(pos, z1, true);       pos += 4;
    dv.setFloat32(pos, x2, true);       pos += 4;
    dv.setFloat32(pos, y2, true);       pos += 4;
    dv.setFloat32(pos, z2, true);       pos += 4;
    pos += 2;  // attribute byte count
  }
  return buf;
}

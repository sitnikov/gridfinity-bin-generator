"""
Verify our generated bins against the official-style Gridfinity Specification
(grizzie17, Printables 417152). All numeric checks are derived directly from
the PDF dimension drawings.

Run: ./venv/bin/python verify_spec.py
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass

import gridfinity as G


# ---------------------------------------------------------------------------
# STL utilities (read-only)
# ---------------------------------------------------------------------------

def stl_vertices(path: str):
    """Return (Nx3) float32 vertex list and bbox of an STL file."""
    with open(path, "rb") as f:
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
        verts = []
        mn = [1e18] * 3
        mx = [-1e18] * 3
        for _ in range(n):
            f.read(12)  # normal
            for _v in range(3):
                v = struct.unpack("<3f", f.read(12))
                verts.append(v)
                for i in range(3):
                    if v[i] < mn[i]: mn[i] = v[i]
                    if v[i] > mx[i]: mx[i] = v[i]
            f.read(2)
    return verts, mn, mx


def vmin_at(verts, predicate):
    return min((v for v in verts if predicate(v)), key=lambda v: tuple(v), default=None)


# ---------------------------------------------------------------------------
# Spec-derived expected values
# ---------------------------------------------------------------------------

@dataclass
class SpecBin:
    """Reference values from grizzie17 PDF."""
    grid_xy_mm: float = 42.0
    grid_z_mm: float = 7.0
    tolerance_per_side: float = 0.25
    foot_step1_h: float = 0.8     # bottom step
    foot_step2_h: float = 1.8     # mid vertical
    foot_chamfer_h: float = 2.15  # 45° transition
    foot_total_h: float = 4.75
    bin_corner_radius: float = 3.75   # outer fillet (4.0 - tolerance)
    foot_radius_bot: float = 0.8      # = 1.05 - 0.25
    foot_radius_mid: float = 1.6      # = 1.85 - 0.25
    lip_above_top_h: float = 4.4
    lip_section_h: list = None  # [0.7, 1.8, 1.9]

    def __post_init__(self):
        if self.lip_section_h is None:
            self.lip_section_h = [0.7, 1.8, 1.9]

    def expected_outer_xy(self, grids_x, grids_y):
        return (grids_x * self.grid_xy_mm - 2 * self.tolerance_per_side,
                grids_y * self.grid_xy_mm - 2 * self.tolerance_per_side)

    def expected_total_z(self, grids_z, has_lip=True, rounded_lip=True):
        h = grids_z * self.grid_z_mm
        if has_lip:
            h += self.lip_above_top_h
            if rounded_lip:
                # SCAD source clips the very top by 0.75 mm (h5 in stacklip)
                h -= 0.75
        return h


SPEC = SpecBin()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

PASS = "OK"
FAIL = "FAIL"

results = []

def check(name: str, actual, expected, tol=0.05):
    if abs(actual - expected) <= tol:
        results.append((PASS, name, f"{actual:.3f} ≈ {expected:.3f}  (Δ={actual-expected:+.3f})"))
    else:
        results.append((FAIL, name, f"{actual:.3f} vs {expected:.3f}  (Δ={actual-expected:+.3f}, tol={tol})"))


def verify_bin(grids_x, grids_y, grids_z, label):
    print(f"\n=== {label} ({grids_x}×{grids_y}×{grids_z}) ===")
    p = G.GridfinityParams(grids_x=grids_x, grids_y=grids_y, grids_z=grids_z)
    path = f"/tmp/spec_{label}.stl"
    G.export(p, path)
    verts, mn, mx = stl_vertices(path)

    # 1. Outer footprint
    ex_x, ex_y = SPEC.expected_outer_xy(grids_x, grids_y)
    actual_x = mx[0] - mn[0]
    actual_y = mx[1] - mn[1]
    check(f"  outer X (expect {grids_x}×42 - 0.5)", actual_x, ex_x)
    check(f"  outer Y (expect {grids_y}×42 - 0.5)", actual_y, ex_y)

    # 2. Total Z (with stacking lip, rounded top accounted for)
    ex_z = SPEC.expected_total_z(grids_z)
    actual_z = mx[2] - mn[2]
    check(f"  total Z (lip top, after 0.75mm chop)", actual_z, ex_z, tol=0.1)

    # 3. Foot bottom z = 0
    check(f"  foot bottom z", mn[2], 0.0, tol=0.01)

    # 4. Foot top transition: at z = foot_total_h, body cylinder begins
    # Find vertices near z = 4.75; their min XY radius from corner should equal bin_corner_radius
    z_target = SPEC.foot_total_h
    near_foot_top = [v for v in verts if abs(v[2] - z_target) < 0.05]
    print(f"  vertices near z={z_target}: {len(near_foot_top)}")
    if near_foot_top:
        # Most-central vertex should be inside the rounded rect; outermost X
        # should be outer_x/2
        max_x_at_top = max(v[0] for v in near_foot_top)
        # bin centered at 0
        check(f"  foot top outer X (= {ex_x/2})", max_x_at_top, ex_x / 2, tol=0.05)

    # 5. Foot bottom outline: at z=0, inset by ~2.95 mm from outer
    near_floor = [v for v in verts if abs(v[2]) < 0.01]
    if near_floor:
        max_x_floor = max(v[0] for v in near_floor)
        # spec: outer at z=0 is inset by 2.95 from bin's outer plane
        # bin outer half-width = ex_x/2; foot bottom extends to ex_x/2 - (foot_inset)
        # foot_inset comes from the 45° chamfer + step + tolerance
        # spec dimension "2.95" is horizontal length of foot profile from outer
        # to where the 45° chamfer starts at the bottom
        expected_floor_x = ex_x / 2 - 2.95
        check(f"  foot bottom outline X (spec 2.95 inset)", max_x_floor, expected_floor_x, tol=0.1)


# ---------------------------------------------------------------------------
# Run checks
# ---------------------------------------------------------------------------

verify_bin(1, 1, 1, "1x1x1")
verify_bin(1, 1, 3, "1x1x3")
verify_bin(2, 2, 2, "2x2x2")
verify_bin(3, 2, 6, "3x2x6")

print("\n" + "=" * 60)
n_pass = sum(1 for r in results if r[0] == PASS)
n_fail = len(results) - n_pass
print(f"  {n_pass} passed, {n_fail} failed of {len(results)} checks")
print("=" * 60)
for status, name, info in results:
    marker = "✓" if status == PASS else "✗"
    print(f" {marker} {name:50s}  {info}")
sys.exit(0 if n_fail == 0 else 1)

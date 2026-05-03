"""
Compare our generator output against reference STL bins from
"Gridfinity Lite Economical Plain Storage Bins" (Printables 265271).

The reference set is *not* HuMa_Meng's Ultra Light bins — it's a different
gridfinity-compatible bin family.  Inner cavities, wall thickness, lip details
will differ, but for stackability the things that *must* match are:

  1. Outer footprint X/Y at z=0   (so two bins fit the same baseplate)
  2. Total Z height               (so a stack stays uniform)
  3. Foot-bottom outline radii    (so the foot of bin B drops into the
     stacking lip pocket of bin A below)

For each reference STL:
  - Read bbox + the z=0 silhouette + a slice near the top
  - Build our equivalent params and read the same metrics
  - Report mismatches
"""
from __future__ import annotations

import os
import struct
import sys
import re

import gridfinity as G

REF_ROOT = ("/Users/sitnikov/Documents/Claude/gridfinity_web_generator_clode/"
            "gridfinity-lite-economical-plain-storage-bins-model_files")


# ---------------------------------------------------------------------------
# STL utilities
# ---------------------------------------------------------------------------

def stl_read(path: str):
    """Read both ASCII and binary STL formats."""
    with open(path, "rb") as f:
        head = f.read(5)
        f.seek(0)
        if head == b"solid":
            # Could be ASCII or binary (binary headers can start with 'solid'),
            # so peek at the second line.
            first = f.readline()
            second = f.readline()
            f.seek(0)
            if b"facet" in second or b"endsolid" in second:
                return _stl_read_ascii(f)
        return _stl_read_binary(f)


def _stl_read_binary(f) -> list:
    f.seek(80)
    n = struct.unpack("<I", f.read(4))[0]
    verts = []
    for _ in range(n):
        f.read(12)
        for _v in range(3):
            verts.append(struct.unpack("<3f", f.read(12)))
        f.read(2)
    return verts


def _stl_read_ascii(f) -> list:
    verts = []
    for line in f:
        s = line.strip()
        if s.startswith(b"vertex"):
            parts = s.split()
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return verts


def bbox(verts):
    mn = [1e18] * 3
    mx = [-1e18] * 3
    for v in verts:
        for i in range(3):
            if v[i] < mn[i]: mn[i] = v[i]
            if v[i] > mx[i]: mx[i] = v[i]
    return mn, mx


def slice_near_z(verts, z, tol=0.05):
    return [v for v in verts if abs(v[2] - z) < tol]


def xy_extent(verts):
    """Return min/max in X and Y for the slice."""
    if not verts:
        return None
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]
    return (min(xs), max(xs), min(ys), max(ys))


def silhouette_radii(verts_at_z):
    """Min and max distance from the bbox-center in XY for the slice."""
    if not verts_at_z:
        return None, None
    xs = [v[0] for v in verts_at_z]
    ys = [v[1] for v in verts_at_z]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    import math
    rs = [math.hypot(v[0] - cx, v[1] - cy) for v in verts_at_z]
    return min(rs), max(rs)


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------

NAME_RE = re.compile(r"gridfinity-lite-(\d+)x(\d+)x(\d+)\.stl")

def list_reference_bins():
    found = []
    for sub in ("3 High", "6 High", "9 High", "12 High"):
        d = os.path.join(REF_ROOT, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            m = NAME_RE.match(fn)
            if m:
                gx, gy, gz = (int(g) for g in m.groups())
                found.append((gx, gy, gz, os.path.join(d, fn)))
    return found


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def outer_x_at_z(verts, z, tol=0.05):
    """Width of the outer silhouette at a given Z level.  We use 'a couple of
    layers thick' tol to make sure we always catch a vertex ring."""
    sl = [v for v in verts if abs(v[2] - z) < tol]
    if not sl:
        return None
    xs = [v[0] for v in sl]
    return max(xs) - min(xs)


def compare_one(gx: int, gy: int, gz: int, ref_path: str, verbose: bool = False):
    """Return dict of metrics."""
    ref_verts = stl_read(ref_path)
    ref_mn, ref_mx = bbox(ref_verts)

    p = G.GridfinityParams(grids_x=gx, grids_y=gy, grids_z=gz)
    our_part = G.build_bin(p)
    our_path = "/tmp/_our_for_ref.stl"
    with open(our_path, "wb") as f:
        f.write(G.to_stl_bytes(our_part))
    our_verts = stl_read(our_path)
    our_mn, our_mx = bbox(our_verts)

    ref_sz = [ref_mx[i] - ref_mn[i] for i in range(3)]
    our_sz = [our_mx[i] - our_mn[i] for i in range(3)]

    # Compare the outer silhouette at several heights — these are the only
    # surfaces that matter for stackability and baseplate compatibility.
    z_test_ref = [
        ("foot bottom",     ref_mn[2] + 0.0),          # z=0 outline
        ("foot top",        ref_mn[2] + 4.75),         # transition into body
        ("body mid",        ref_mn[2] + ref_sz[2] / 2),
        ("lip valley",      ref_mx[2] - 4.4 + 1.5),    # inside the lip
        ("lip max",         ref_mx[2] - 0.5),          # near top
    ]
    diffs = []
    for label, z_ref in z_test_ref:
        z_our = z_ref - ref_mn[2] + our_mn[2]
        ref_x = outer_x_at_z(ref_verts, z_ref, tol=0.3)
        our_x = outer_x_at_z(our_verts, z_our, tol=0.3)
        diffs.append((label, ref_x, our_x))

    return {
        "size": (gx, gy, gz),
        "ref_sz": ref_sz, "our_sz": our_sz,
        "diffs": diffs,
        "ref_path": ref_path,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    refs = list_reference_bins()
    if not refs:
        print(f"No reference bins found under {REF_ROOT}")
        sys.exit(1)
    # Sample: pick a representative subset across sizes and heights
    sample_keys = [
        (1, 1, 3),  (1, 2, 3),  (2, 2, 3),  (3, 3, 3),  (5, 6, 3),
        (1, 1, 6),  (2, 3, 6),  (4, 4, 6),
        (1, 1, 9),  (3, 3, 9),
        (1, 1, 12), (5, 5, 12),
    ]
    sample_set = set(sample_keys)
    refs_sample = [r for r in refs if (r[0], r[1], r[2]) in sample_set]

    rows = []
    for gx, gy, gz, path in refs_sample:
        rows.append(compare_one(gx, gy, gz, path))

    # ---- Top-level: bbox comparison ----
    print(f"\n{'size':9s}  {'ref XYZ':22s}  {'our XYZ':22s}  {'ΔXYZ':22s}")
    print("-" * 90)
    bad_outer = []
    for r in rows:
        sz = r["size"]
        ref_sz = r["ref_sz"]; our_sz = r["our_sz"]
        d = [our_sz[i] - ref_sz[i] for i in range(3)]
        ref_str = f"{ref_sz[0]:6.2f} {ref_sz[1]:6.2f} {ref_sz[2]:6.2f}"
        our_str = f"{our_sz[0]:6.2f} {our_sz[1]:6.2f} {our_sz[2]:6.2f}"
        d_str = f"{d[0]:+5.2f} {d[1]:+5.2f} {d[2]:+5.2f}"
        flag = ""
        if any(abs(d[i]) > 0.1 for i in (0, 1)) or abs(d[2]) > 0.5:
            flag = "  ← bbox fail"
            bad_outer.append(r)
        print(f"{sz[0]}x{sz[1]}x{sz[2]:<5}  {ref_str}  {our_str}  {d_str}{flag}")

    # ---- Mid-detail: outer silhouette at characteristic Z levels ----
    print("\nOuter silhouette width at characteristic Z heights (X dimension only):")
    print(f"{'size':9s}  {'foot bot':18s}  {'foot top':18s}  {'body mid':18s}  {'lip valley':18s}  {'lip max':18s}")
    print("-" * 130)
    bad_profile = []
    for r in rows:
        sz = r["size"]
        cells = []
        any_bad = False
        for label, ref_x, our_x in r["diffs"]:
            if ref_x is None or our_x is None:
                cells.append("    -    /    -    ")
                continue
            d = our_x - ref_x
            cells.append(f"{ref_x:6.2f}/{our_x:6.2f} ({d:+.2f})")
            # tolerance: outer profile should agree to within 0.5 mm at any z
            if abs(d) > 0.5:
                any_bad = True
        if any_bad:
            bad_profile.append(r)
        size_str = f"{sz[0]}x{sz[1]}x{sz[2]}"
        print(f"{size_str:9s}  " + "  ".join(cells))

    print()
    print(f"Outer XY/Z (overall):     {len(rows)-len(bad_outer)}/{len(rows)} match within tolerance")
    print(f"Outer profile (5 Z slices): {len(rows)-len(bad_profile)}/{len(rows)} match within 0.5 mm")
    return 0 if (not bad_outer and not bad_profile) else 1


if __name__ == "__main__":
    sys.exit(main())

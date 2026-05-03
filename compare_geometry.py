"""
Compare manifold3d vs build123d geometry on a grid of presets.

For each preset:
  - generate STL with both backends
  - print bbox, volume, triangle count
  - flag if bbox/volume disagree by more than tolerance
"""
from __future__ import annotations

import os
import struct
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import gridfinity as G_MFD
import gridfinity_b123 as G_B123


def stl_stats(path: str):
    with open(path, "rb") as f:
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
        mn = [1e18, 1e18, 1e18]
        mx = [-1e18, -1e18, -1e18]
        # Approximate volume via signed tetrahedral volume to (0,0,0)
        vol6 = 0.0
        for _ in range(n):
            f.read(12)  # normal
            tri = []
            for _v in range(3):
                v = struct.unpack("<3f", f.read(12))
                tri.append(v)
                for i in range(3):
                    if v[i] < mn[i]: mn[i] = v[i]
                    if v[i] > mx[i]: mx[i] = v[i]
            f.read(2)  # attr
            a, b, c = tri
            vol6 += (a[0] * (b[1] * c[2] - b[2] * c[1])
                     - a[1] * (b[0] * c[2] - b[2] * c[0])
                     + a[2] * (b[0] * c[1] - b[1] * c[0]))
        return n, mn, mx, vol6 / 6.0


def cmp(name: str, params):
    out_mfd = f"/tmp/cmp_mfd_{name}.stl"
    out_b123 = f"/tmp/cmp_b123_{name}.stl"

    p_mfd = G_MFD.GridfinityParams(**{k: v for k, v in params.items()
                                       if k in G_MFD.GridfinityParams.__dataclass_fields__})
    p_b123 = G_B123.GridfinityParams(**{k: v for k, v in params.items()
                                         if k in G_B123.GridfinityParams.__dataclass_fields__})

    t = time.perf_counter()
    G_MFD.export(p_mfd, out_mfd)
    t_mfd = time.perf_counter() - t

    t = time.perf_counter()
    G_B123.export(p_b123, out_b123)
    t_b123 = time.perf_counter() - t

    n_m, mn_m, mx_m, vol_m = stl_stats(out_mfd)
    n_b, mn_b, mx_b, vol_b = stl_stats(out_b123)

    bbox_diff = max(abs(mn_m[i] - mn_b[i]) for i in range(3)) + max(abs(mx_m[i] - mx_b[i]) for i in range(3))
    vol_diff_pct = abs(vol_m - vol_b) / max(abs(vol_b), 1e-9) * 100

    flag = "OK"
    if bbox_diff > 0.5:
        flag = "BBOX_DIFF"
    elif vol_diff_pct > 5.0:
        flag = "VOL_DIFF"

    print(f"{name:18s}  {flag}")
    print(f"  mfd:    {t_mfd*1000:6.0f}ms  tris={n_m:6d}  vol={vol_m:9.1f}  bbox=[{mn_m[0]:6.1f},{mn_m[1]:6.1f},{mn_m[2]:6.1f}]→[{mx_m[0]:6.1f},{mx_m[1]:6.1f},{mx_m[2]:6.1f}]")
    print(f"  b123:   {t_b123*1000:6.0f}ms  tris={n_b:6d}  vol={vol_b:9.1f}  bbox=[{mn_b[0]:6.1f},{mn_b[1]:6.1f},{mn_b[2]:6.1f}]→[{mx_b[0]:6.1f},{mx_b[1]:6.1f},{mx_b[2]:6.1f}]")
    print(f"  Δbbox={bbox_diff:.3f}mm  Δvol={vol_diff_pct:.2f}%")
    print()
    return flag == "OK"


cases = [
    ("default", {}),
    ("magnets", {"magnets": True}),
    ("dividers", {"dividers": True, "dividers_x": 1, "dividers_y": 2}),
    ("scoops", {"scoops": True}),
    ("labels_full", {"labels": True, "label_position": "Full"}),
    ("labels_left", {"labels": True, "label_position": "Left",
                     "dividers": True, "dividers_x": 1, "dividers_y": 1}),
    ("half_grid", {"grids_x": 1.5, "grids_y": 2.5}),
    ("half_grid_base", {"half_grid_base": True}),
    ("solid_base", {"ultra_light_base": False}),
    ("all_features", {"magnets": True, "dividers": True, "dividers_x": 1, "dividers_y": 1,
                      "labels": True, "label_position": "Center", "scoops": True}),
    ("big", {"grids_x": 3, "grids_y": 3, "grids_z": 6, "magnets": True}),
]

ok = 0
total = len(cases)
for name, params in cases:
    if cmp(name, params):
        ok += 1
print(f"=== {ok}/{total} matched ===")
sys.exit(0 if ok == total else 1)

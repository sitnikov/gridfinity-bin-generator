# Gridfinity Web Generator — notes for Claude

Web generator for Gridfinity bins. Python port of `UltraLightGridfinityBins.scad`
(HuMa\_Meng) → Flask + Three.js. CSG engine — **manifold3d** (mesh-CSG in C++).

## Run

Python 3.10–3.12. The OCP backend (build123d) doesn't build on 3.13/3.14:

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py     # http://127.0.0.1:5050/
```

All scripts assume `cwd = repo root` (relative `gridfinity` import).

## Architecture

| File                            | Role                                                   |
|---------------------------------|--------------------------------------------------------|
| `gridfinity.py`                 | manifold3d CAD engine (1:1 SCAD port)                  |
| `gridfinity_b123.py`            | Old build123d backend — kept as a CAD reference only   |
| `app.py`                        | Flask: GET `/`, POST `/generate`, LRU STL cache        |
| `templates/index.html`          | Form + Three.js viewer                                 |
| `compare_geometry.py`           | Regression: bbox/volume manifold vs build123d          |
| `verify_spec.py`                | Conformance vs the official Gridfinity spec            |
| `verify_reference.py`           | Stackability vs reference STLs (Printables 265271)     |
| `gridfinity_specification.pdf`  | Local copy of the spec (grizzie17, MIT)                |
| `UltraLightGridfinityBins.scad` | Upstream SCAD — source of truth                        |

Reference STLs are **not bundled in the repo** (see README). Download them
separately into `gridfinity-lite-economical-plain-storage-bins-model_files/`
to run `verify_reference.py`.

## Key design decisions

### Backend: manifold3d, not build123d

We started on build123d (NURBS / OpenCascade) — ~0.8–4 s per bin due to
expensive boolean ops. Rewrote on manifold3d (mesh-CSG): now 30–200 ms,
~20× faster. build123d is preserved in `gridfinity_b123.py` only as a
regression-test reference — **not used in production**.

### SCAD → manifold3d mapping

Every SCAD construct is translated literally. **Do not simplify or optimise
the geometry** — we mirror `UltraLightGridfinityBins.scad` 1:1:

| SCAD                    | manifold3d                              |
|-------------------------|-----------------------------------------|
| `cube`, `cylinder`      | `Manifold.cube`, `Manifold.cylinder`    |
| `translate`, `mirror`   | `.translate()`, `.mirror()`             |
| `union` / `difference`  | `+` / `-`                               |
| `hull() { 4 cylinders }`| `Manifold.batch_hull([…])`              |

If you add a feature, find the equivalent in the SCAD source and translate
it in the same style. Don't loft, don't simplify — a convex hull of 4
cylinders is **exactly the same geometry** as in SCAD CGAL.

### CSG robustness: EPS_VOID

manifold3d (like any mesh-CSG) breaks on **coplanar surfaces** — if a void
in `_diff_all` has a face that exactly coincides with the outer surface,
the subtract leaves a zero-thickness shell and subsequent subtracts fail.

Solved via `_hull4_void()`: the void is grown by `EPS_VOID = 1e-3` mm in
all directions. That's 100× below 3D-printer precision, but eliminates the
CGAL/manifold robustness issues.

Used **only in `_make_bin_stacklip`**, where void and outer have matching
radii. If you add a new difference and see odd artefacts at the top —
check for coplanar surfaces and replace `_hull4` with `_hull4_void` for
the voids.

### Cylinder discretization

Adaptive, like OpenSCAD: `FA = 8°`, `FS = 0.25 mm` (values from the
`[Hidden]` section of the original SCAD). Each cylinder gets
`segments = max(5, min(⌈360/FA⌉, ⌈2π·r/FS⌉))` via `_segments_for_radius()`.

This produces the exact same triangulation as OpenSCAD itself — on 3×3×6
with all features, our volume differs from the OpenSCAD render by
**0.0025 %** (≈3 mm³), bbox X/Y matches exactly. Small radii get fewer
segments (e.g. r=0.6 → 16), large radii get more (r=8 → 45).

`CIRCULAR_SEGMENTS = 32` is kept as a fallback but is effectively unused —
every `_cyl()` call routes through the adaptive counter.

### `_unit_xy(p)` and `Half-sized base`

SCAD pairs the `Half_Grid_Base` toggle with two synchronised changes:
`Grids_X_/Grids_Y_ = 2 × Grids_X/Y` AND `Basic_Unit_XY = 0.5 × 42.0`.
Net external size is unchanged; the base is just split into 4× more
smaller feet.

Earlier the Python port doubled the count but kept `BASIC_UNIT_XY = 42.0`
fixed → external dimensions came out 2× too big. Now there's a
`_unit_xy(p)` helper that returns 21 mm when `half_grid_base` is on, and
all `_make_*` functions use that instead of the constant. Don't undo
this.

### Magnet position deviates from spec

HuMa\_Meng's SCAD places magnets at `(BASIC_RADIUS_2, BASIC_RADIUS_2) = (8, 8)`
from the grid-unit corner, while the Gridfinity spec says 4.8 mm from the
outer face (= 5.05 from the unit corner with offset). This is a
**deliberate deviation in the upstream SCAD**, not a bug. Documented in
README. Only change if a user explicitly asks — otherwise we break the
1:1 correspondence with the source.

### Server-side STL cache

LRU of 32 entries + per-key Lock. Key = sorted tuple of `asdict(params)`.
Repeat requests (debounce flapping, returning to a prior value) — <1 ms.

## Tests

All three scripts run from the repo root with no arguments and exit
non-zero if anything diverges:

```bash
./venv/bin/python verify_spec.py        # 24/24 spec checkpoints
./venv/bin/python verify_reference.py   # vs Printables 265271 (need to download STLs)
./venv/bin/python compare_geometry.py   # vs build123d (needs build123d)
```

Before committing geometry changes, **always run `verify_spec.py`** —
that's the baseline. `compare_geometry.py` is optional and pulls in the
heavy build123d.

## Gotchas

* **Don't use Python 3.13/3.14** — `cadquery-ocp` has no wheels, so
  build123d won't install. 3.12 is the sweet spot.
* **Don't run tests without `cd <repo>`** — modules import relative to cwd.
* **Reference STLs in `gridfinity-lite-...-model_files/` are ASCII-STL.**
  A binary reader will crash on them. `verify_reference.py` supports both
  formats — don't break that.
* **`_diff_all` / `_union_all` filter empty parts** via `is_empty()`. If
  a module can return an empty `Manifold()`, that's fine — filtering
  handles it.
* **0.75 mm at the very top of the lip** is `h5` in SCAD code, an
  intentional cut. Spec gives 24.69 mm for 1×1×3 (R0.5 fillet), reference
  STL gives 24.80, ours gives 24.65. All within 0.15 mm — don't "fix".
* **Half-grid (`grids_x = 1.5`)**: in SCAD it's a special mirror mode,
  see `_mirror_xy()`. If you change base/clean, run `verify_spec.py`
  including the half-grid presets (already in there).

## Conventions

* **Don't add features that aren't in the upstream SCAD** without an
  explicit user request. This project is a port, not a fork in spirit.
* **Coordinates inside `_make_*` functions are in "module-local" units**
  (where start_x/start_y = corner of the grid unit or footprint). The
  translation to the final frame happens in `build_bin()` via
  `_mirror_xy()` and the final `translate([-Wx/2, -Wy/2, 0])`.
* **All dimensions are in mm.** EPS = `1e-3` mm (= 1 µm). Tolerance
  thresholds: `0.001` for CSG-eps, `0.05` for geometry, `0.5` for
  stackability.
* **Don't pull build123d into `requirements.txt`** — it's heavy (200 MB
  of OCP) and only needed for `compare_geometry.py`. Anyone who wants
  it can install it themselves.

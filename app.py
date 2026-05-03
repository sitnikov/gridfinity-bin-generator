"""
Web frontend for the Gridfinity bin generator.

Routes:
  GET  /            -- HTML form + Three.js viewer
  POST /generate    -- JSON params -> STL bytes (model/x.stl-binary)
"""
from __future__ import annotations

import io
import os
import warnings
from collections import OrderedDict
from dataclasses import asdict
from threading import Lock

from flask import Flask, jsonify, render_template, request, send_file

import gridfinity as G

# OCP boolean cleanup warnings are noisy and harmless — silence at the source.
warnings.filterwarnings("ignore", message="Boolean operation unable to clean")
warnings.filterwarnings("ignore", message="Unable to clean")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# LRU cache for STL bytes
# ---------------------------------------------------------------------------

_CACHE_MAX = 32
_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_cache_lock = Lock()
# Per-key locks so two concurrent requests for the same params share work
# instead of both running build_bin in parallel.
_inflight: "dict[tuple, Lock]" = {}
_inflight_lock = Lock()


def _cache_get(key: tuple) -> bytes | None:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _cache_put(key: tuple, data: bytes) -> None:
    with _cache_lock:
        _cache[key] = data
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Param parsing
# ---------------------------------------------------------------------------

def _params_from_request() -> G.GridfinityParams:
    """Build GridfinityParams from a JSON POST body, using defaults for any
    missing fields and raising on unknown ones."""
    data = request.get_json(silent=True) or {}
    defaults = asdict(G.GridfinityParams())
    unknown = [k for k in data.keys() if k not in defaults]
    if unknown:
        raise ValueError(f"Unknown parameter(s): {', '.join(unknown)}")
    merged = {**defaults, **data}
    # Coerce numeric/bool fields
    coerce_int = {"dividers_x", "dividers_y"}
    coerce_float = {
        "grids_x", "grids_y", "grids_z", "wall_thickness", "magnet_diameter",
        "magnet_depth", "label_width", "label_depth", "scoop_radius",
        "label_support_density", "ultra_light_floor_thickness",
    }
    coerce_bool = {
        "half_grid_right", "half_grid_top", "half_grid_base",
        "ultra_light_base", "ultra_light_labels",
        "magnets", "dividers", "labels", "label_for_each_section", "scoops",
    }
    for k in coerce_int:
        merged[k] = int(merged[k])
    for k in coerce_float:
        merged[k] = float(merged[k])
    for k in coerce_bool:
        v = merged[k]
        if isinstance(v, str):
            merged[k] = v.lower() in ("1", "true", "yes", "on")
        else:
            merged[k] = bool(v)
    if merged["label_position"] not in ("Full", "Left", "Center", "Right"):
        raise ValueError(f"Invalid label_position: {merged['label_position']}")
    return G.GridfinityParams(**merged)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", defaults=asdict(G.GridfinityParams()))


def _generate_stl(params: G.GridfinityParams) -> bytes:
    """Build the STL bytes for given params, sharing work between concurrent
    requests for the same params."""
    key = tuple(sorted(asdict(params).items()))
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # Acquire a per-key lock so concurrent identical requests don't double-build
    with _inflight_lock:
        lk = _inflight.get(key)
        if lk is None:
            lk = Lock()
            _inflight[key] = lk
    with lk:
        cached = _cache_get(key)
        if cached is not None:
            return cached
        part = G.build_bin(params)
        data = G.to_stl_bytes(part)
        _cache_put(key, data)
        with _inflight_lock:
            _inflight.pop(key, None)
        return data


def _build_filename(p: G.GridfinityParams, ext: str) -> str:
    """Compose a descriptive filename that encodes the parameters that matter
    for telling two bins apart. Mirrors ``buildFilename`` in templates/index.html
    — keep them in sync.
    """
    parts = [f"gridfinity_{p.grids_x:g}x{p.grids_y:g}x{p.grids_z:g}"]
    parts.append(f"w{p.wall_thickness:g}")
    if p.half_grid_right:     parts.append("hr")
    if p.half_grid_top:       parts.append("ht")
    if p.half_grid_base:      parts.append("hb")
    if p.ultra_light_base:
        parts.append("ulb")
        if p.ultra_light_floor_thickness > p.wall_thickness:
            parts.append(f"bot{p.ultra_light_floor_thickness:g}")
    if p.ultra_light_labels:
        parts.append("ull")
        if p.label_support_density != 1.0:
            parts.append(f"lsd{p.label_support_density:g}")
    if p.magnets:
        parts.append(f"m{p.magnet_diameter:g}-{p.magnet_depth:g}")
    if p.dividers and (p.dividers_x or p.dividers_y):
        parts.append(f"div{p.dividers_x}x{p.dividers_y}")
    if p.labels:
        pos = p.label_position[0]  # F/L/C/R
        a = "a" if p.label_for_each_section else ""
        parts.append(f"lbl{pos}{a}-{p.label_width:g}x{p.label_depth:g}")
    if p.scoops:
        parts.append(f"sc{p.scoop_radius:g}")
    return "_".join(parts) + ext


@app.route("/generate", methods=["POST"])
def generate():
    """Build the STL for the given parameters and return its bytes.

    Query args:
      ?download=1   – send as attachment (disposition + filename)
    """
    try:
        params = _params_from_request()
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400

    data = _generate_stl(params)

    download = request.args.get("download") in ("1", "true")
    fname = _build_filename(params, ".stl")
    return send_file(
        io.BytesIO(data),
        mimetype="model/stl",
        as_attachment=download,
        download_name=fname,
    )


if __name__ == "__main__":
    # threaded=True so previews don't queue behind in-flight generations
    app.run(host="127.0.0.1", port=5050, debug=True, threaded=True)

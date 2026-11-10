"""Printability gate: slice with PrusaSlicer's automatic supports and report supports the coral adds.

The part is sliced twice with identical placement, once as the host alone (baseline) and once with
the coral. Support extrusions in the second run that lie farther than `tolerance` from any
baseline support extrusion on a nearby layer are support the coral needs. PrusaSlicer is the
judge here because it is what will actually print the part.

Slicing settings come from a full PrusaSlicer config (see prusa_profile); supports are switched on
in automatic mode with the given threshold, everything else (layer height, extrusion widths) is the
profile's.

  python -m coralgen.slicecheck RESULT.stl --baseline HOST.stl --profile MINI.ini --threshold 0 ...
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import trimesh
from scipy.spatial import cKDTree

_XY = re.compile(r"X(-?[\d.]+)\s+Y(-?[\d.]+)")
_SUPPORT_TYPES = ("Support material", "Support material interface")


@dataclasses.dataclass
class SupportReport:
    added_points: int
    layers: list[float]
    bbox_min: list[float] | None
    bbox_max: list[float] | None


def _support_points(gcode: pathlib.Path) -> dict[float, np.ndarray]:
    z = None
    kind = None
    pts: dict[float, list[tuple[float, float]]] = {}
    with gcode.open() as f:
        for line in f:
            if line.startswith(";Z:"):
                z = round(float(line[3:]), 3)
            elif line.startswith(";TYPE:"):
                kind = line[6:].strip()
            elif kind in _SUPPORT_TYPES and line.startswith("G1") and " E" in line:
                m = _XY.search(line)
                if m and z is not None:
                    pts.setdefault(z, []).append((float(m.group(1)), float(m.group(2))))
    return {k: np.array(v) for k, v in pts.items()}


def _slice(stl: pathlib.Path, gcode: pathlib.Path, profile: pathlib.Path, threshold: float,
           slicer: str) -> None:
    # The support extrusions are read from text G-code; printer profiles may default to binary
    text_gcode = gcode.with_suffix(".text_gcode.ini")
    text_gcode.write_text("binary_gcode = 0\n")
    cmd = [slicer, "--export-gcode", "--dont-arrange", "--load", str(profile), "--load", str(text_gcode),
           "--support-material", "--support-material-auto",
           "--support-material-threshold", str(threshold),
           "-o", str(gcode), str(stl)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not gcode.exists():
        raise RuntimeError(f"PrusaSlicer failed on {stl}:\n{res.stdout}\n{res.stderr}")


def added_supports(result: pathlib.Path, baseline: pathlib.Path, profile: pathlib.Path,
                   threshold: float, tolerance: float, z_window: float,
                   bed_center: tuple[float, float]) -> SupportReport:
    slicer = shutil.which("prusa-slicer")
    if slicer is None:
        raise RuntimeError("prusa-slicer is not on PATH")
    res_mesh = trimesh.load(result, force="mesh")
    base_mesh = trimesh.load(baseline, force="mesh")
    # One shift for both, taken from the result, so their supports stay comparable point by point
    lo, hi = res_mesh.bounds
    shift = np.array([bed_center[0] - (lo[0] + hi[0]) / 2, bed_center[1] - (lo[1] + hi[1]) / 2, -lo[2]])
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        out = {}
        for name, mesh in (("result", res_mesh), ("baseline", base_mesh)):
            stl = t / f"{name}.stl"
            mesh.copy().apply_translation(shift).export(stl)
            _slice(stl, t / f"{name}.gcode", profile, threshold, slicer)
            out[name] = _support_points(t / f"{name}.gcode")
    base_layers = sorted(out["baseline"])
    added = []
    layers = []
    for z, pts in sorted(out["result"].items()):
        # Support layers are re-synchronised per object, so their heights differ between runs
        near = [out["baseline"][k] for k in base_layers if abs(k - z) <= z_window]
        if near:
            d, _ = cKDTree(np.vstack(near)).query(pts)
            pts = pts[d > tolerance]
        if len(pts):
            added.append(np.column_stack([pts, np.full(len(pts), z)]))
            layers.append(z)
    if not added:
        return SupportReport(0, [], None, None)
    a = np.vstack(added) - shift
    return SupportReport(len(a), layers, a.min(0).round(2).tolist(), a.max(0).round(2).tolist())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result", type=pathlib.Path)
    ap.add_argument("--baseline", type=pathlib.Path, required=True, help="host alone, same frame")
    ap.add_argument("--profile", type=pathlib.Path, required=True, help="full PrusaSlicer config (.ini)")
    ap.add_argument("--threshold", type=float, required=True,
                    help="support overhang threshold, deg (0 = PrusaSlicer automatic detection)")
    ap.add_argument("--tolerance", type=float, required=True,
                    help="support points closer than this to baseline support are not counted, mm")
    ap.add_argument("--z-window", type=float, required=True,
                    help="baseline support layers within this height difference are compared, mm")
    ap.add_argument("--bed-center", type=float, nargs=2, required=True, metavar=("X", "Y"))
    args = ap.parse_args(argv)
    rep = added_supports(args.result, args.baseline, args.profile, args.threshold, args.tolerance,
                         args.z_window, tuple(args.bed_center))
    print(dataclasses.asdict(rep))
    return 1 if rep.added_points else 0


if __name__ == "__main__":
    sys.exit(main())

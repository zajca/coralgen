"""coralgen command line.

  coralgen grow   CONFIG   skeleton JSON + low-poly preview STL (seconds)
  coralgen mesh   CONFIG   full solid from the saved skeleton: STL + 3MF (host + coral, coral only)
  coralgen verify CONFIG   slice host vs result in PrusaSlicer; exit 1 if the coral adds support
  coralgen build  CONFIG   grow + mesh + verify
  coralgen search CONFIG   build with random_seed, random_seed + 1, ... (verify.max_attempts tries)
                           until one passes verify; exit 1 if none does

The report JSON next to the outputs records every step (and every search attempt).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tempfile
import time

from . import config as config_mod
from .geometry import GeometryError
from .grow import GrowthError, Skeleton, grow
from .mesh import build, preview, split_parts
from .prusa_profile import ProfileError, bed_center, merged_config, write_ini
from .slicecheck import added_supports


def _paths(cfg: config_mod.Config) -> dict[str, pathlib.Path]:
    d, n = cfg.output.dir, cfg.output.name
    return {
        "skeleton": d / f"{n}_skeleton.json",
        "preview": d / f"{n}_preview.stl",
        "stl": d / f"{n}.stl",
        "3mf": d / f"{n}.3mf",
        "coral": d / f"{n}_coral_only.stl",
        "report": d / f"{n}_report.json",
    }


def _part_path(cfg: config_mod.Config, name: str, host: bool = False) -> pathlib.Path:
    """Printable piece (print orientation); the host-only piece is the verify baseline."""
    suffix = "_host" if host else ""
    return cfg.output.dir / f"{cfg.output.name}_part_{name}{suffix}.stl"


def _report(path: pathlib.Path, key: str, data: object, fresh: bool = False) -> None:
    old = {} if fresh or not path.exists() else json.loads(path.read_text())
    old[key] = data
    path.write_text(json.dumps(old, indent=2))


def cmd_grow(cfg: config_mod.Config, keep: dict | None = None) -> dict:
    p = _paths(cfg)
    t = time.perf_counter()
    skel, rep = grow(cfg)
    skel.save(p["skeleton"])
    preview(cfg, skel).export(p["preview"])
    info = dataclasses.asdict(rep) | {"random_seed": cfg.growth.random_seed,
                                      "seconds": round(time.perf_counter() - t, 2)}
    _report(p["report"], "grow", info, fresh=True)
    for k, v in (keep or {}).items():
        _report(p["report"], k, v)
    print(f"grow: {info}\n  -> {p['skeleton']}\n  -> {p['preview']}")
    return info


def cmd_mesh(cfg: config_mod.Config) -> dict:
    p = _paths(cfg)
    if not p["skeleton"].exists():
        raise SystemExit(f"{p['skeleton']} not found: run 'coralgen grow' first")
    t = time.perf_counter()
    result, coral, rep = build(cfg, Skeleton.load(p["skeleton"]))
    result.export(p["stl"])
    result.export(p["3mf"])
    coral.export(p["coral"])
    pieces = []
    for name, piece, host_piece in split_parts(cfg, result):
        piece.export(_part_path(cfg, name))
        host_piece.export(_part_path(cfg, name, host=True))
        pieces.append(str(_part_path(cfg, name)))
    info = dataclasses.asdict(rep) | {"parts": pieces, "seconds": round(time.perf_counter() - t, 2)}
    _report(p["report"], "mesh", info)
    print(f"mesh: {info}\n  -> {p['stl']}\n  -> {p['3mf']}\n  -> {p['coral']}")
    return info


def cmd_verify(cfg: config_mod.Config) -> dict:
    p = _paths(cfg)
    if not p["stl"].exists():
        raise SystemExit(f"{p['stl']} not found: run 'coralgen mesh' first")
    v = cfg.verify
    t = time.perf_counter()
    profile = merged_config(v.vendor_bundle, v.print_preset, v.printer_preset, v.filament_preset)
    # Each printed piece is judged in its own print orientation; without [[part]] the whole result
    pairs = ([(pt.name, _part_path(cfg, pt.name), _part_path(cfg, pt.name, host=True)) for pt in cfg.part]
             or [("whole", p["stl"], cfg.host.stl)])
    pieces = {}
    with tempfile.TemporaryDirectory() as tmp:
        ini = pathlib.Path(tmp) / "profile.ini"
        write_ini(profile, ini)
        for name, piece, host_piece in pairs:
            if not piece.exists():
                raise SystemExit(f"{piece} not found: run 'coralgen mesh' first")
            rep = added_supports(piece, host_piece, ini, v.support_threshold, v.tolerance,
                                 v.z_window, bed_center(profile))
            pieces[name] = dataclasses.asdict(rep)
    added = sum(r["added_points"] for r in pieces.values())
    info = {"added_points": added, "passed": added == 0, "pieces": pieces,
            "printer": v.printer_preset, "print": v.print_preset,
            "seconds": round(time.perf_counter() - t, 2)}
    _report(p["report"], "verify", info)
    print(f"verify: {'PASS' if info['passed'] else 'FAIL'} {info}")
    return info


def cmd_search(cfg: config_mod.Config) -> bool:
    attempts: list[dict] = []
    for i in range(cfg.verify.max_attempts):
        seed = cfg.growth.random_seed + i
        c = dataclasses.replace(cfg, growth=dataclasses.replace(cfg.growth, random_seed=seed))
        try:
            grow_info = cmd_grow(c, keep={"search": attempts})
        except GrowthError as e:
            attempts.append({"random_seed": seed, "error": str(e)})
            _report(_paths(c)["report"], "search", attempts, fresh=True)
            print(f"search: random_seed {seed}: {e}", file=sys.stderr)
            continue
        try:
            mesh_info = cmd_mesh(c)
        except GeometryError as e:
            attempts.append({"random_seed": seed, "error": str(e)})
            _report(_paths(c)["report"], "search", attempts)
            print(f"search: random_seed {seed}: {e}", file=sys.stderr)
            continue
        ver = cmd_verify(c)
        attempts.append({"random_seed": seed, "passed": ver["passed"], "nodes": grow_info["nodes"],
                         "added_support_points": ver["added_points"],
                         "coral_volume": mesh_info["coral_volume"]})
        _report(_paths(c)["report"], "search", attempts)
        if ver["passed"]:
            print(f"search: random_seed {seed} passed after {i + 1} attempt(s)")
            return True
    print(f"search: none of {cfg.verify.max_attempts} seeds passed; the outputs on disk are the last "
          "FAILED attempt, see the report", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="coralgen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["grow", "mesh", "verify", "build", "search"])
    ap.add_argument("config", type=pathlib.Path)
    args = ap.parse_args(argv)
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as e:
        print(f"{args.config}: {e}", file=sys.stderr)
        return 2
    cfg.output.dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "search":
            return 0 if cmd_search(cfg) else 1
        if args.command in ("grow", "build"):
            cmd_grow(cfg)
        if args.command in ("mesh", "build"):
            cmd_mesh(cfg)
        if args.command in ("verify", "build"):
            return 0 if cmd_verify(cfg)["passed"] else 1
    except (GrowthError, GeometryError, ProfileError) as e:
        print(f"{args.config}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

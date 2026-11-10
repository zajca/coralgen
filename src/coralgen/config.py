"""Coral generator configuration.

Every parameter comes from a TOML file. Missing or unknown keys are errors: there are no
built-in defaults, so a run is fully described by its config file. Relative paths in the
file are resolved against the directory of the config file.
"""
from __future__ import annotations

import dataclasses
import pathlib
import tomllib
from typing import Any, get_type_hints


class ConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class HostConfig:
    stl: pathlib.Path            # part to overgrow, in its print orientation (+Z up, bed at z min)
    cut_stl: pathlib.Path | None       # volume removed from the coral after meshing (e.g. the cavity
                                       # behind the walls the roots are anchored in); growth ignores it
    keepout_stl: pathlib.Path | None   # volume branches must avoid by keepout_margin and that is also
                                       # removed after meshing (ports, lid lift path); same frame


@dataclasses.dataclass(frozen=True)
class SeedConfig:
    count: int                   # wanted number of branch roots
    min_spacing: float           # mm between roots
    z_min: float                 # roots only between these heights (print frame, mm)
    z_max: float
    min_normal_z: float          # roots only on faces whose normal z >= this (0 = vertical walls)
    root_embed: float            # extra depth (mm) beyond the root radius that the root extension
                                 # reaches into the host, so its rounded end stays inside
    surface_samples: int         # candidate points sampled on the host surface
    max_hull_depth: float        # roots only this close to the host's convex hull, which keeps them
                                 # out of pockets, channels and cavities (mm)


@dataclasses.dataclass(frozen=True)
class EnvelopeConfig:
    spread: float                # coral stays within this distance from the host surface (mm)
    height_above_top: float      # coral may rise this far above the host top (mm)
    shape: str                   # "volume": space colonisation in the envelope; "branching": see
                                 # [branching]; "crawl": creeping over the host surface, see [crawl]
    attractor_count: int         # volume mode only
    xy_margin: float             # attractors stay within the host footprint grown by this much (mm)
    host_clearance: float        # free distance from the host once a branch has left its root
    keepout_margin: float        # minimum distance of any branch axis from the keep-out volume
    field_voxel: float           # resolution of the distance fields used while growing (mm)


@dataclasses.dataclass(frozen=True)
class BranchingConfig:
    """Recursive growth for envelope.shape = "branching": one forking colony per root."""
    trunk_length: float          # first branch length before the first fork (mm)
    length_ratio: float          # each fork level is this fraction of the previous length
    max_forks: int               # fork levels per colony
    fork_angle_min_deg: float    # angle between the two branches of a fork
    fork_angle_max_deg: float
    fork_twist_deg: float        # turn of the fork plane per level: 0 = flat fan, 90 = bushy
    wander_deg: float            # random direction change per step (standard deviation)
    azimuth_jitter_deg: float    # random turn of the first fork plane away from facing the host centre


@dataclasses.dataclass(frozen=True)
class CrawlConfig:
    """Surface growth for envelope.shape = "crawl": coral creeping over the host surface."""
    surface_samples: int         # points sampled on the host surface; growth snaps to them
    attractor_count: int         # surface samples the coral grows towards
    center_height_ratio: float   # branch axis height over the surface, in branch radii (sunk below 1)
    snap_limit_ratio: float      # a step may move at most this many step lengths when snapped
    smooth_iterations: int       # passes that pull each path node towards its neighbours
    polyp_probability: float     # chance that a node on an upward face sprouts a polyp
    polyp_length_min: float      # polyp length range (mm); polyps stand vertically
    polyp_length_max: float


@dataclasses.dataclass(frozen=True)
class PartConfig:
    """A printed piece cut out of the result: z_min <= z < z_max of the run frame."""
    name: str
    z_min: float
    z_max: float
    flip: bool                   # printed upside down (rotated 180 deg about X)


@dataclasses.dataclass(frozen=True)
class GrowthConfig:
    step: float                  # segment length (mm)
    influence: float             # attractor influence radius (mm)
    kill: float                  # attractor is consumed when a node comes this close (mm)
    max_tilt_deg: float          # every segment stays within this angle from vertical
    inertia: float               # weight of the parent direction in the new direction
    upward_bias: float           # weight of +Z in the new direction
    max_iterations: int
    min_twig_nodes: int          # side branches shorter than this many nodes are pruned
    branch_gap: float            # surface gap kept between unrelated branches, mm
    random_seed: int


@dataclasses.dataclass(frozen=True)
class RadiusConfig:
    tip: float                   # branch tip radius (mm)
    max: float                   # trunk radius cap (mm)
    pipe_exponent: float         # r_parent^e = sum(r_child^e)


@dataclasses.dataclass(frozen=True)
class MeshConfig:
    voxel: float                 # SDF grid resolution (mm)
    taubin_iterations: int
    preview_sides: int           # polygon sides of the low-poly preview cylinders


@dataclasses.dataclass(frozen=True)
class VerifyConfig:
    vendor_bundle: pathlib.Path  # PrusaSlicer vendor bundle with the system presets
    printer_preset: str
    print_preset: str
    filament_preset: str
    support_threshold: float     # deg; 0 = PrusaSlicer automatic overhang detection
    tolerance: float             # support points this close to the host's own support are ignored, mm
    z_window: float              # host support layers within this height are compared, mm
    max_attempts: int            # seeds tried by `coralgen search` before giving up


@dataclasses.dataclass(frozen=True)
class OutputConfig:
    dir: pathlib.Path
    name: str


@dataclasses.dataclass(frozen=True)
class Config:
    host: HostConfig
    seed: SeedConfig
    envelope: EnvelopeConfig
    branching: BranchingConfig
    crawl: CrawlConfig
    growth: GrowthConfig
    radius: RadiusConfig
    mesh: MeshConfig
    verify: VerifyConfig
    output: OutputConfig
    part: list[PartConfig]       # [[part]] tables; empty = the whole result is one printed piece


_SECTIONS = get_type_hints(Config)


def _build(cls: type, section: str, raw: dict[str, Any], base: pathlib.Path) -> Any:
    hints = get_type_hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(raw) - set(names))
    if unknown:
        raise ConfigError(f"[{section}] unknown key(s): {', '.join(unknown)}")
    values = {}
    for name in names:
        if name not in raw:
            raise ConfigError(f"[{section}] missing required key '{name}'")
        val = raw[name]
        hint = hints[name]
        optional_path = hint == (pathlib.Path | None)
        if hint is pathlib.Path or optional_path:
            if optional_path and val == "":
                values[name] = None
                continue
            if not isinstance(val, str):
                raise ConfigError(f"[{section}] '{name}' must be a path string")
            p = pathlib.Path(val).expanduser()
            values[name] = (p if p.is_absolute() else base / p).resolve()
        elif hint is bool:
            if not isinstance(val, bool):
                raise ConfigError(f"[{section}] '{name}' must be true or false")
            values[name] = val
        elif hint is int:
            if not isinstance(val, int) or isinstance(val, bool):
                raise ConfigError(f"[{section}] '{name}' must be an integer")
            values[name] = val
        elif hint is float:
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ConfigError(f"[{section}] '{name}' must be a number")
            values[name] = float(val)
        elif hint is str:
            if not isinstance(val, str) or not val:
                raise ConfigError(f"[{section}] '{name}' must be a non-empty string")
            values[name] = val
        else:
            raise ConfigError(f"[{section}] '{name}': unsupported type {hint}")
    return cls(**values)


def _validate(cfg: Config) -> None:
    checks = [
        (cfg.seed.count > 0, "seed.count must be > 0"),
        (cfg.seed.z_max > cfg.seed.z_min, "seed.z_max must be > seed.z_min"),
        (-1.0 <= cfg.seed.min_normal_z <= 1.0, "seed.min_normal_z must be in [-1, 1]"),
        (0 < cfg.growth.kill < cfg.growth.influence, "growth: need 0 < kill < influence"),
        (0 < cfg.growth.max_tilt_deg < 90, "growth.max_tilt_deg must be in (0, 90)"),
        (cfg.growth.step > 0, "growth.step must be > 0"),
        (0 < cfg.radius.tip <= cfg.radius.max, "radius: need 0 < tip <= max"),
        (cfg.radius.pipe_exponent >= 1, "radius.pipe_exponent must be >= 1"),
        (cfg.mesh.voxel > 0 and cfg.envelope.field_voxel > 0, "voxel sizes must be > 0"),
        (cfg.envelope.shape in ("volume", "branching", "crawl"),
         'envelope.shape must be "volume", "branching" or "crawl"'),
        (0 <= cfg.crawl.center_height_ratio < 1, "crawl.center_height_ratio must be in [0, 1)"),
        (cfg.crawl.snap_limit_ratio > 0, "crawl.snap_limit_ratio must be > 0"),
        (cfg.crawl.smooth_iterations >= 0, "crawl.smooth_iterations must be >= 0"),
        (0 <= cfg.crawl.polyp_probability <= 1, "crawl.polyp_probability must be in [0, 1]"),
        (0 < cfg.crawl.polyp_length_min <= cfg.crawl.polyp_length_max,
         "crawl: need 0 < polyp_length_min <= polyp_length_max"),
        (all(pt.z_max > pt.z_min for pt in cfg.part), "part: need z_max > z_min"),
        (len({pt.name for pt in cfg.part}) == len(cfg.part), "part: names must be unique"),
        (cfg.branching.trunk_length > 0 and 0 < cfg.branching.length_ratio <= 1,
         "branching: need trunk_length > 0, 0 < length_ratio <= 1"),
        (0 <= cfg.branching.fork_angle_min_deg <= cfg.branching.fork_angle_max_deg,
         "branching: need 0 <= fork_angle_min_deg <= fork_angle_max_deg"),
        (cfg.branching.max_forks >= 0 and cfg.branching.wander_deg >= 0,
         "branching: max_forks and wander_deg must be >= 0"),
        (cfg.verify.max_attempts >= 1, "verify.max_attempts must be >= 1"),
        (cfg.mesh.preview_sides >= 3, "mesh.preview_sides must be >= 3"),
        (cfg.growth.branch_gap > 0, "growth.branch_gap must be > 0"),
        (cfg.envelope.host_clearance >= cfg.radius.max + cfg.growth.branch_gap,
         "envelope.host_clearance must be >= radius.max + growth.branch_gap, or a branch passing "
         "the host leaves a thin air gap under itself that needs support"),
        (cfg.envelope.keepout_margin >= cfg.radius.max,
         "envelope.keepout_margin must be >= radius.max (branch surfaces must stay out of the keep-out)"),
    ]
    for ok, msg in checks:
        if not ok:
            raise ConfigError(msg)


def from_dict(raw: dict[str, Any], base: pathlib.Path) -> Config:
    unknown = sorted(set(raw) - set(_SECTIONS))
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(unknown)}")
    parts = {}
    for name, cls in _SECTIONS.items():
        if name not in raw:
            raise ConfigError(f"missing section [{name}]")
        if name == "part":
            if not isinstance(raw[name], list):
                raise ConfigError("'part' must be a list of [[part]] tables")
            parts[name] = [_build(PartConfig, f"part {i}", t, base) for i, t in enumerate(raw[name])]
        else:
            parts[name] = _build(cls, name, raw[name], base)
    cfg = Config(**parts)
    _validate(cfg)
    return cfg


def load(path: pathlib.Path) -> Config:
    path = pathlib.Path(path).resolve()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return from_dict(raw, path.parent)

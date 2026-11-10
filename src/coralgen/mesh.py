"""Skeleton -> printable solid.

Branches become tapered capsules united in a voxel signed-distance field.
The surface is extracted with marching cubes, smoothed, cut by the cut/keep-out volumes and fused
with the host as an exact manifold boolean. Printability comes from the skeleton (every segment
within the tilt cone, unrelated branches apart, root ends buried in material); it is verified by
slicing, see slicecheck.
"""
from __future__ import annotations

import dataclasses

import manifold3d
import numpy as np
import trimesh
from skimage.measure import marching_cubes

from .config import Config
from .geometry import GeometryError, Grid, from_manifold, load_mesh, to_manifold
from .grow import Skeleton, root_anchor

# Field value far outside every branch; only its sign and the blend range matter
_FAR = np.float32(1e3)


@dataclasses.dataclass
class MeshReport:
    segments: int
    grid_shape: tuple[int, int, int]
    coral_volume: float
    result_volume: float


def _root_segments(skel: Skeleton, embed: float, max_tilt_deg: float) -> tuple[np.ndarray, ...]:
    """Extension of each root into the host, so the branch joins it without a kink or a bulge."""
    roots = np.nonzero(skel.parent < 0)[0]
    r = skel.radius[roots]
    a = root_anchor(skel.pos[roots], skel.root_dir[roots], skel.root_normal[roots], r, embed, max_tilt_deg)
    return a, skel.pos[roots], r, r


def all_segments(skel: Skeleton, cfg: Config) -> tuple[np.ndarray, ...]:
    branch = skel.segments()
    root = _root_segments(skel, cfg.seed.root_embed, cfg.growth.max_tilt_deg)
    return tuple(np.concatenate([b, r]) for b, r in zip(branch, root))


def branch_field(a: np.ndarray, b: np.ndarray, ra: np.ndarray, rb: np.ndarray, grid: Grid) -> np.ndarray:
    """Signed distance of the union of tapered capsules, evaluated per capsule bounding box.

    The union is a plain minimum. A smooth minimum would swell every joint of overlapping
    consecutive capsules into a ring bulge, and on a branch's underside such a bulge is a local
    overhang far steeper than the branch itself.
    """
    f = np.full(grid.shape, _FAR, dtype=np.float32)
    xs, ys, zs = (grid.axis(i).astype(np.float32) for i in range(3))
    reach = np.maximum(ra, rb) + grid.res
    lo = np.minimum(a, b) - reach[:, None]
    hi = np.maximum(a, b) + reach[:, None]
    i0 = np.clip(np.floor((lo - grid.origin) / grid.res).astype(int), 0, np.array(grid.shape))
    i1 = np.clip(np.ceil((hi - grid.origin) / grid.res).astype(int) + 1, 0, np.array(grid.shape))
    for s in range(len(a)):
        (x0, y0, z0), (x1, y1, z1) = i0[s], i1[s]
        if x0 >= x1 or y0 >= y1 or z0 >= z1:
            continue
        px = xs[x0:x1, None, None] - a[s, 0]
        py = ys[None, y0:y1, None] - a[s, 1]
        pz = zs[None, None, z0:z1] - a[s, 2]
        ba = (b[s] - a[s]).astype(np.float32)
        bb = float(ba @ ba)
        t = np.clip((px * ba[0] + py * ba[1] + pz * ba[2]) / max(bb, 1e-12), 0.0, 1.0)
        d = np.sqrt((px - t * ba[0]) ** 2 + (py - t * ba[1]) ** 2 + (pz - t * ba[2]) ** 2)
        d -= ra[s] + t * (rb[s] - ra[s])
        np.minimum(f[x0:x1, y0:y1, z0:z1], d, out=f[x0:x1, y0:y1, z0:z1])
    return f


def _surface(field: np.ndarray, grid: Grid) -> trimesh.Trimesh:
    padded = np.pad(field, 1, constant_values=_FAR)
    # Degenerate (zero-area) triangles would be dropped when vertices are merged, leaving holes
    verts, faces, _, _ = marching_cubes(padded, level=0.0, spacing=(grid.res,) * 3,
                                        gradient_direction="ascent", allow_degenerate=False)
    # Vertices are merged in grid coordinates and moved afterwards: merging after the shift rounds
    # differently and can fuse nearby vertices into non-manifold edges
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    mesh.apply_translation(grid.origin - grid.res)
    # Smoothing an open surface drags boundary vertices far away, so stop here instead
    if not mesh.is_watertight:
        raise GeometryError("marching cubes produced an open surface")
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def build(cfg: Config, skel: Skeleton) -> tuple[trimesh.Trimesh, trimesh.Trimesh, MeshReport]:
    """Returns (host fused with coral, coral alone after cuts, report)."""
    host = load_mesh(cfg.host.stl)
    host_m = to_manifold(host, f"host {cfg.host.stl.name}")
    remove = manifold3d.Manifold()
    for path, what in ((cfg.host.cut_stl, "cut"), (cfg.host.keepout_stl, "keep-out")):
        if path is not None:
            remove = remove + to_manifold(load_mesh(path), f"{what} {path.name}")

    a, b, ra, rb = all_segments(skel, cfg)
    m = cfg.mesh
    pad = float(max(ra.max(), rb.max())) + 3 * m.voxel
    lo = np.minimum(a.min(0), b.min(0)) - pad
    hi = np.maximum(a.max(0), b.max(0)) + pad
    lo[2] = max(lo[2], host.bounds[0][2])
    grid = Grid.around(lo, hi, m.voxel)
    field = branch_field(a, b, ra, rb, grid)

    coral = _surface(field, grid)
    if m.taubin_iterations > 0:
        trimesh.smoothing.filter_taubin(coral, iterations=m.taubin_iterations)
    coral_m = to_manifold(coral, "coral surface")
    if not remove.is_empty():
        coral_m = coral_m - remove
    # Nothing below the bed: marching cubes closes the surface half a voxel under the grid floor
    coral_m = coral_m.trim_by_plane((0.0, 0.0, 1.0), float(host.bounds[0][2]))
    result_m = host_m + coral_m
    report = MeshReport(segments=len(a), grid_shape=grid.shape, coral_volume=float(coral_m.volume()),
                        result_volume=float(result_m.volume()))
    return from_manifold(result_m), from_manifold(coral_m), report


def split_parts(cfg: Config, result: trimesh.Trimesh) -> list[tuple[str, trimesh.Trimesh, trimesh.Trimesh]]:
    """[(name, piece with coral, host piece)] in print orientation, for every [[part]].

    A piece is the slab z_min <= z < z_max of the run frame, turned upside down when flip is set and
    put on the bed; the host piece gets the same transform so the two slice comparably.
    """
    host_m = to_manifold(load_mesh(cfg.host.stl), f"host {cfg.host.stl.name}")
    res_m = to_manifold(result, "result")
    out = []
    for pt in cfg.part:
        slab = manifold3d.Manifold.cube([2000.0, 2000.0, pt.z_max - pt.z_min]).translate([-1000.0, -1000.0, pt.z_min])
        pieces = [res_m ^ slab, host_m ^ slab]
        if pt.flip:
            pieces = [m.rotate([180.0, 0.0, 0.0]) for m in pieces]
        z0 = pieces[0].bounding_box()[2]
        pieces = [m.translate([0.0, 0.0, -z0]) for m in pieces]
        out.append((pt.name, from_manifold(pieces[0]), from_manifold(pieces[1])))
    return out


def preview(cfg: Config, skel: Skeleton) -> trimesh.Trimesh:
    """Low-poly stand-in: one coarse cylinder per segment plus the host."""
    a, b, ra, rb = all_segments(skel, cfg)
    parts = [load_mesh(cfg.host.stl)]
    for s in range(len(a)):
        if np.linalg.norm(b[s] - a[s]) < 1e-6:
            continue
        parts.append(trimesh.creation.cylinder(radius=0.5 * (ra[s] + rb[s]), segment=[a[s], b[s]],
                                               sections=cfg.mesh.preview_sides))
    return trimesh.util.concatenate(parts)

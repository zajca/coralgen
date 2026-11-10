"""Mesh loading, manifold conversion and voxel rasterisation shared by growth and meshing."""
from __future__ import annotations

import dataclasses
import pathlib

import manifold3d
import numpy as np
import trimesh
from scipy import ndimage
from skimage.draw import polygon2mask

# Slice planes are nudged off the voxel-centre height (as a fraction of the voxel size) so a plane
# never lies on a horizontal face of the mesh: within manifold3d's tolerance of a face the
# cross-section may come back empty.
_SLICE_NUDGE = 0.01


class GeometryError(RuntimeError):
    pass


def load_mesh(path: pathlib.Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise GeometryError(f"{path}: no triangle mesh found")
    return mesh


def to_manifold(mesh: trimesh.Trimesh, what: str) -> manifold3d.Manifold:
    m = manifold3d.Manifold(manifold3d.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
    ))
    if m.status() != manifold3d.Error.NoError:
        raise GeometryError(f"{what} is not a valid closed manifold ({m.status()})")
    return m


def from_manifold(m: manifold3d.Manifold) -> trimesh.Trimesh:
    out = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(out.vert_properties)[:, :3],
                           faces=np.asarray(out.tri_verts), process=True)


@dataclasses.dataclass(frozen=True)
class Grid:
    """Regular voxel grid; voxel (i, j, k) has its centre at origin + (i, j, k) * res."""
    origin: np.ndarray
    res: float
    shape: tuple[int, int, int]

    @staticmethod
    def around(lo: np.ndarray, hi: np.ndarray, res: float) -> "Grid":
        lo = np.asarray(lo, dtype=float)
        hi = np.asarray(hi, dtype=float)
        shape = tuple(int(n) for n in np.ceil((hi - lo) / res).astype(int) + 1)
        return Grid(origin=lo, res=float(res), shape=shape)

    def axis(self, a: int) -> np.ndarray:
        return self.origin[a] + np.arange(self.shape[a]) * self.res

    def index(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Nearest voxel index of each point and whether it lies inside the grid."""
        ijk = np.rint((np.atleast_2d(pts) - self.origin) / self.res).astype(int)
        ok = np.all((ijk >= 0) & (ijk < np.array(self.shape)), axis=1)
        return np.clip(ijk, 0, np.array(self.shape) - 1), ok

    def sample(self, field: np.ndarray, pts: np.ndarray, outside: float) -> np.ndarray:
        ijk, ok = self.index(pts)
        vals = field[ijk[:, 0], ijk[:, 1], ijk[:, 2]]
        return np.where(ok, vals, outside)


def rasterize(m: manifold3d.Manifold, grid: Grid) -> np.ndarray:
    """Boolean occupancy of a closed manifold on the grid (voxel centres inside the solid)."""
    occ = np.zeros(grid.shape, dtype=bool)
    if m.is_empty():
        return occ
    bb = m.bounding_box()            # (xmin, ymin, zmin, xmax, ymax, zmax)
    zs = grid.axis(2) + _SLICE_NUDGE * grid.res
    xy0 = grid.origin[:2]
    for k in np.nonzero((zs >= bb[2]) & (zs <= bb[5]))[0]:
        layer = np.zeros(grid.shape[:2], dtype=bool)
        for poly in m.slice(float(zs[k])).to_polygons():
            if len(poly) < 3:
                continue
            # Even-odd fill: XOR of every contour handles holes regardless of winding
            layer ^= polygon2mask(grid.shape[:2], (np.asarray(poly) - xy0) / grid.res)
        occ[:, :, k] = layer
    return occ


def outside_distance(occ: np.ndarray, res: float) -> np.ndarray:
    """Distance (mm) from each voxel centre to the nearest occupied voxel; 0 inside."""
    if not occ.any():
        return np.full(occ.shape, np.inf, dtype=np.float32)
    return (ndimage.distance_transform_edt(~occ) * res).astype(np.float32)

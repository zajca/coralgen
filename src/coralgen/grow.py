"""Coral skeleton growth constrained for FDM printing.

Two growth modes share every printability rule:
  envelope.shape = "volume": space colonisation (Runions et al. 2007) towards attractors that fill
                             the envelope; bushy, irregular colonies.
  envelope.shape = "branching": one recursive colony per root: a trunk that forks again and
                             again; flat sea fans or bushy staghorns depending on fork_twist_deg.

Every segment points upwards within `max_tilt_deg` of vertical, so a branch's underside never
overhangs more than that angle and the coral prints without supports. Branches start on the
host surface, keep clear of the host once they have left it, and never enter the keep-out volume.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

from .config import Config
from .geometry import Grid, load_mesh, outside_distance, rasterize, to_manifold

SKELETON_FORMAT = 1


class GrowthError(RuntimeError):
    """The host, its volumes and the parameters leave no room to grow."""


_UP = np.array([0.0, 0.0, 1.0])


@dataclasses.dataclass
class Skeleton:
    """Branch graph. Parents always have a lower index than their children; roots have parent -1."""
    pos: np.ndarray          # (N, 3) node positions, mm
    parent: np.ndarray       # (N,) parent index or -1
    radius: np.ndarray       # (N,) branch radius at the node, mm
    root_dir: np.ndarray     # (N, 3) first growth direction for roots, zero for other nodes
    root_normal: np.ndarray  # (N, 3) host surface normal at roots, zero for other nodes

    def segments(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        child = np.nonzero(self.parent >= 0)[0]
        par = self.parent[child]
        return self.pos[par], self.pos[child], self.radius[par], self.radius[child]

    def save(self, path: pathlib.Path) -> None:
        data = {
            "format": SKELETON_FORMAT,
            "pos": np.round(self.pos, 4).tolist(),
            "parent": self.parent.tolist(),
            "radius": np.round(self.radius, 4).tolist(),
            "root_dir": np.round(self.root_dir, 6).tolist(),
            "root_normal": np.round(self.root_normal, 6).tolist(),
        }
        path.write_text(json.dumps(data))

    @staticmethod
    def load(path: pathlib.Path) -> "Skeleton":
        data = json.loads(path.read_text())
        if data.get("format") != SKELETON_FORMAT:
            raise ValueError(f"{path}: unsupported skeleton format {data.get('format')}")
        return Skeleton(
            pos=np.array(data["pos"], dtype=float).reshape(-1, 3),
            parent=np.array(data["parent"], dtype=int),
            radius=np.array(data["radius"], dtype=float),
            root_dir=np.array(data["root_dir"], dtype=float).reshape(-1, 3),
            root_normal=np.array(data["root_normal"], dtype=float).reshape(-1, 3),
        )


def clamp_to_cone(v: np.ndarray, max_tilt_deg: float) -> np.ndarray:
    """Unit vectors no further than max_tilt from +Z; steeper ones are pulled up to the cone edge.

    A vector with no horizontal component and pointing down has no defined cone direction and
    becomes straight up.
    """
    v = np.atleast_2d(np.asarray(v, dtype=float))
    n = np.linalg.norm(v, axis=1, keepdims=True)
    u = np.divide(v, n, out=np.tile(_UP, (len(v), 1)), where=n > 1e-12)
    cos_t = np.cos(np.radians(max_tilt_deg))
    steep = u[:, 2] < cos_t
    h = u[:, :2]
    hn = np.linalg.norm(h, axis=1)
    fix = steep & (hn > 1e-9)
    out = u.copy()
    sin_t = np.sin(np.radians(max_tilt_deg))
    out[fix, :2] = h[fix] / hn[fix, None] * sin_t
    out[fix, 2] = cos_t
    out[steep & ~fix] = _UP
    return out


def pipe_radii(parent: np.ndarray, tip: float, rmax: float, exponent: float) -> np.ndarray:
    """Da Vinci / pipe model: r_parent^e = sum of r_child^e, leaves get `tip`, capped at `rmax`."""
    n = len(parent)
    acc = np.zeros(n)
    r = np.zeros(n)
    for i in range(n - 1, -1, -1):
        r[i] = tip if acc[i] == 0 else min(rmax, acc[i] ** (1.0 / exponent))
        if parent[i] >= 0:
            acc[parent[i]] += r[i] ** exponent
    return r


def prune_twigs(parent: np.ndarray, min_nodes: int) -> np.ndarray:
    """Keep-mask that drops side twigs shorter than min_nodes (counted from their fork)."""
    n = len(parent)
    children = np.zeros(n, dtype=int)
    np.add.at(children, parent[parent >= 0], 1)
    keep = np.ones(n, dtype=bool)
    for leaf in np.nonzero(children == 0)[0]:
        chain = [leaf]
        i = parent[leaf]
        while i >= 0 and children[i] == 1:
            chain.append(i)
            i = parent[i]
        # i < 0: the chain is a whole root branch, not a side twig
        if i >= 0 and len(chain) < min_nodes:
            keep[chain] = False
    # Roots that never grew would leave a bare stub on the host
    keep[(parent < 0) & (children == 0)] = False
    return keep


@dataclasses.dataclass
class GrowthReport:
    roots: int
    attractors: int
    iterations: int
    nodes: int
    pruned: int


def _occupancy(path: pathlib.Path | None, what: str, grid: Grid) -> np.ndarray:
    if path is None:
        return np.zeros(grid.shape, dtype=bool)
    return rasterize(to_manifold(load_mesh(path), f"{what} {path.name}"), grid)


class _Fields:
    """Distance lookups on a voxel grid: to the host, the cut and keep-out volumes (from outside)
    and the depth inside host-or-cut material (from inside)."""

    def __init__(self, cfg: Config, host: trimesh.Trimesh):
        env = cfg.envelope
        lo, hi = host.bounds
        pad = env.spread + cfg.radius.max + env.keepout_margin
        self.top = hi[2]
        self.host_lo, self.host_hi = lo, hi
        # Below the host by a root anchor's reach plus its radius: anchors may end in a cut volume
        # under a thin host, and their depth must be measurable there
        below = 2 * cfg.radius.max + cfg.seed.root_embed
        self.grid = Grid.around(
            np.array([lo[0] - pad, lo[1] - pad, lo[2] - below]),
            np.array([hi[0] + pad, hi[1] + pad, hi[2] + env.height_above_top + cfg.radius.max]),
            env.field_voxel,
        )
        res = self.grid.res
        host_occ = rasterize(to_manifold(host, f"host {cfg.host.stl.name}"), self.grid)
        cut_occ = _occupancy(cfg.host.cut_stl, "cut", self.grid)
        self.host = outside_distance(host_occ, res)
        self.cut = outside_distance(cut_occ, res)
        self.keep = outside_distance(_occupancy(cfg.host.keepout_stl, "keep-out", self.grid), res)
        self.depth = (ndimage.distance_transform_edt(host_occ | cut_occ) * res).astype(np.float32)

    def solid_depth(self, p: np.ndarray) -> np.ndarray:
        return self.grid.sample(self.depth, p, outside=0.0)

    def host_dist(self, p: np.ndarray) -> np.ndarray:
        return self.grid.sample(self.host, p, outside=-1.0)

    def cut_dist(self, p: np.ndarray) -> np.ndarray:
        return self.grid.sample(self.cut, p, outside=-1.0)

    def keep_dist(self, p: np.ndarray) -> np.ndarray:
        return self.grid.sample(self.keep, p, outside=-1.0)


def root_anchor(pos: np.ndarray, direction: np.ndarray, normal: np.ndarray, radius: np.ndarray,
                embed: float, max_tilt_deg: float) -> np.ndarray:
    """Inner end of each root's extension into the host, collinear with its first direction.

    It lies radius + `embed` deep along the surface normal, so the rounded end of the extension
    stays behind the surface instead of bulging out below the branch. A root on a vertical wall
    leaves it at the cone edge, where the depth per unit length is sin(max_tilt); half of that
    bounds the length on faces that lean slightly downwards.
    """
    ratio = np.maximum(np.einsum("ij,ij->i", direction, normal), 0.5 * np.sin(np.radians(max_tilt_deg)))
    return pos - direction * ((radius + embed) / ratio)[:, None]


def hull_depth(mesh: trimesh.Trimesh, pts: np.ndarray) -> np.ndarray:
    """Distance of points inside the convex hull of `mesh` from the hull surface (0 on it)."""
    hull = mesh.convex_hull
    offs = np.einsum("ij,ij->i", hull.face_normals, hull.triangles[:, 0])
    return np.clip(np.min(offs[None, :] - pts @ hull.face_normals.T, axis=1), 0.0, None)


def _seed_roots(cfg: Config, host: trimesh.Trimesh, fields: _Fields,
                rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    s = cfg.seed
    pts, face = trimesh.sample.sample_surface_even(host, s.surface_samples,
                                                   seed=int(rng.integers(2**31)))
    nrm = host.face_normals[face]
    rmax = np.full(len(pts), cfg.radius.max)
    anchor = root_anchor(pts, clamp_to_cone(nrm, cfg.growth.max_tilt_deg), nrm, rmax,
                         s.root_embed, cfg.growth.max_tilt_deg)
    # The root's own cross-section (radius.max around it, just under the surface) must rest on
    # material; next to an edge or chamfer the branch base would hang over it.
    ring = []
    for a in np.radians(np.arange(0, 360, 45)):
        t1 = np.cross(nrm, np.where(np.abs(nrm[:, 2:3]) < 0.9, _UP, [1.0, 0.0, 0.0]))
        t1 /= np.linalg.norm(t1, axis=1, keepdims=True)
        t2 = np.cross(nrm, t1)
        ring.append(pts - nrm * s.root_embed + cfg.radius.max * (np.cos(a) * t1 + np.sin(a) * t2))
    on_material = np.logical_and.reduce([fields.solid_depth(q) > 0 for q in ring])
    filters = {
        "face orientation (min_normal_z)": nrm[:, 2] >= s.min_normal_z,
        "height band (z_min..z_max)": (pts[:, 2] >= s.z_min) & (pts[:, 2] <= s.z_max),
        "keep-out margin": fields.keep_dist(pts) >= cfg.envelope.keepout_margin,
        # Solid material behind the root, not the face of a cavity
        "cut volume": fields.cut_dist(pts) >= s.root_embed,
        "convex hull depth (max_hull_depth)": hull_depth(host, pts) <= s.max_hull_depth,
        # The whole rounded end of the root extension must sit inside material (or a cut void that
        # removes it); near an edge, a corner or the bed it would poke out and hang
        "root anchor inside material": fields.solid_depth(anchor) >= rmax,
        "root base on material": on_material,
    }
    ok = np.logical_and.reduce(list(filters.values()))
    if not ok.any():
        left = np.ones(len(pts), dtype=bool)
        lines = []
        for name, mask in filters.items():
            left &= mask
            lines.append(f"  after {name}: {int(left.sum())}")
        raise GrowthError(f"no valid root positions among {len(pts)} surface samples:\n" + "\n".join(lines))
    pts, nrm = pts[ok], nrm[ok]
    order = rng.permutation(len(pts))
    chosen: list[int] = []
    for i in order:
        if len(chosen) == s.count:
            break
        if chosen and np.min(np.linalg.norm(pts[chosen] - pts[i], axis=1)) < s.min_spacing:
            continue
        chosen.append(i)
    return pts[chosen], nrm[chosen]


def _node_ok(cfg: Config, fields: _Fields, npos: np.ndarray, ppos: np.ndarray) -> np.ndarray:
    """Printability and envelope rules for proposed nodes `npos` grown from `ppos`.

    Once a branch has left the host it keeps host_clearance (while still close, it must not get
    any closer); it stays out of the cut and keep-out volumes, under the height limit and over the
    host footprint grown by xy_margin.
    """
    env = cfg.envelope
    dh_new = fields.host_dist(npos)
    ok = (dh_new > 0) & (dh_new >= np.minimum(env.host_clearance, fields.host_dist(ppos)))
    ok &= fields.keep_dist(npos) >= env.keepout_margin
    ok &= fields.cut_dist(npos) > 0
    ok &= npos[:, 2] <= fields.top + env.height_above_top
    ok &= np.all((npos[:, :2] >= fields.host_lo[:2] - env.xy_margin)
                 & (npos[:, :2] <= fields.host_hi[:2] + env.xy_margin), axis=1)
    return ok


def _attractors(cfg: Config, fields: _Fields, rng: np.random.Generator) -> np.ndarray:
    """Attractors filling the envelope (volume mode); rejection sampling with a bounded number
    of rounds, so an impossible envelope fails instead of looping."""
    env = cfg.envelope
    g = fields.grid
    lo = g.origin.copy()
    hi = g.origin + (np.array(g.shape) - 1) * g.res
    found: list[np.ndarray] = []
    total = 0
    for _ in range(64):
        p = rng.uniform(lo, hi, size=(max(env.attractor_count, 1024), 3))
        dh = fields.host_dist(p)
        ok = (dh >= env.host_clearance) & (dh <= env.spread) & (p[:, 2] >= cfg.seed.z_min)
        ok &= _node_ok(cfg, fields, p, p)
        found.append(p[ok])
        total += int(ok.sum())
        if total >= env.attractor_count:
            break
    pts = np.concatenate(found)[: env.attractor_count]
    if len(pts) == 0:
        raise GrowthError("no attractor fits the envelope: check [envelope] limits")
    return pts


def conflict_prune(pos: np.ndarray, parent: np.ndarray, radius: np.ndarray, depth: int,
                   gap: float) -> np.ndarray:
    """Keep-mask that removes the smaller subtree of every unrelated pair closer than r_i + r_j + gap.

    Growth spaces branches by the tip radius; the pipe model thickens them afterwards, which can
    bring old branches into contact. Removing nodes only thins their ancestors, so one pass with
    the radii given is conservative for the result.
    """
    n = len(parent)
    chain = []
    for i in range(n):
        c, j = set(), i
        for _ in range(depth):
            c.add(j)
            j = parent[j]
            if j < 0:
                break
        chain.append(c)
    size = np.ones(n, dtype=int)
    for i in range(n - 1, -1, -1):          # children follow their parents
        if parent[i] >= 0:
            size[parent[i]] += size[i]
    drop = np.zeros(n, dtype=bool)
    reach = 2 * radius.max() + gap
    pairs = cKDTree(pos).query_pairs(reach, output_type="ndarray")
    for i, j in pairs[np.argsort(pairs.max(axis=1))] if len(pairs) else []:
        if drop[i] or drop[j] or (chain[i] & chain[j]):
            continue
        if np.linalg.norm(pos[i] - pos[j]) < radius[i] + radius[j] + gap:
            # Losing the smaller subtree costs the least coral; on a tie the younger one goes
            drop[j if (size[j], j) < (size[i], i) else i] = True
    for i in range(n):                      # parents precede children
        if parent[i] >= 0 and drop[parent[i]]:
            drop[i] = True
    return ~drop


def _separate(cand: np.ndarray, npos: np.ndarray, grow_ids: np.ndarray, tree: cKDTree,
              anc: list[tuple[int, ...]], depth: int, sep: float, dedupe: float) -> np.ndarray:
    """Candidates that keep `sep` from every unrelated node and `dedupe` from every node.

    A candidate is related to a node when their ancestor chains (`anc`, the node itself first)
    share a node, i.e. they belong to the same recent fork. Candidates are accepted in order and
    each accepted one also constrains the rest of this growth step.
    """
    kept: list[int] = []
    kept_pos: list[np.ndarray] = []
    kept_anc: list[set[int]] = []
    for c in cand:
        # The new node's own chain: itself (not yet indexed) plus its parent's chain, cut to depth
        mine = set(anc[grow_ids[c]][: depth - 1])
        ok = True
        for j in tree.query_ball_point(npos[c], sep):
            d = np.linalg.norm(tree.data[j] - npos[c])
            if d < dedupe or not (mine & set(anc[j])):
                ok = False
                break
        if ok:
            for k, p, a in zip(kept, kept_pos, kept_anc):
                d = np.linalg.norm(p - npos[c])
                # Two children of one parent proposed together are a fork, not a duplicate
                twin = grow_ids[k] == grow_ids[c]
                if (d < dedupe and not twin) or (d < sep and not (mine & a)):
                    ok = False
                    break
        if ok:
            kept.append(c)
            kept_pos.append(npos[c])
            kept_anc.append(mine)
    return np.array(kept, dtype=int)


def _compact(par: np.ndarray, keep: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Parent array of the kept nodes (re-indexed) and the old -> new index map (-1 = dropped)."""
    remap = np.full(len(par), -1)
    remap[keep] = np.arange(keep.sum())
    return np.where(par[keep] >= 0, remap[np.maximum(par[keep], 0)], -1), remap


def _expand(mask_kept: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Mask over the kept nodes -> mask over all nodes (dropped nodes stay dropped)."""
    full = np.zeros(len(keep), dtype=bool)
    full[keep] = mask_kept
    return full


@dataclasses.dataclass
class _Tree:
    """Growing node arrays plus the ancestor chains used by the spacing rule."""
    P: np.ndarray
    D: np.ndarray
    parent: list[int]
    anc: list[tuple[int, ...]]
    depth: int

    def add(self, npos: np.ndarray, ndir: np.ndarray, par: np.ndarray) -> None:
        for p in par:
            self.anc.append((len(self.anc),) + self.anc[p][: self.depth - 1])
        self.P = np.vstack([self.P, npos])
        self.D = np.vstack([self.D, ndir])
        self.parent.extend(int(p) for p in par)


def _grow_sca(cfg: Config, fields: _Fields, t: _Tree, sep: float,
              rng: np.random.Generator) -> tuple[int, int]:
    g = cfg.growth
    attr = _attractors(cfg, fields, rng)
    alive = np.ones(len(attr), dtype=bool)
    it = 0
    for it in range(1, g.max_iterations + 1):
        tree = cKDTree(t.P)
        live = np.nonzero(alive)[0]
        if len(live) == 0:
            break
        d, idx = tree.query(attr[live], distance_upper_bound=g.influence)
        hit = np.isfinite(d)
        if not hit.any():
            break
        src, a = idx[hit], attr[live[hit]]
        pull = a - t.P[src]
        pull /= np.maximum(np.linalg.norm(pull, axis=1, keepdims=True), 1e-12)
        acc = np.zeros_like(t.P)
        cnt = np.zeros(len(t.P))
        np.add.at(acc, src, pull)
        np.add.at(cnt, src, 1)
        grow_ids = np.nonzero(cnt > 0)[0]
        want = acc[grow_ids] / cnt[grow_ids, None] + g.inertia * t.D[grow_ids] + g.upward_bias * _UP
        nd = clamp_to_cone(want, g.max_tilt_deg)
        npos = t.P[grow_ids] + g.step * nd
        ok = _node_ok(cfg, fields, npos, t.P[grow_ids])
        # A node whose attractors sit outside its cone keeps proposing the same child: _separate
        # skips candidates that land on an existing node or on another candidate.
        cand = _separate(np.nonzero(ok)[0], npos, grow_ids, tree, t.anc, t.depth, sep, 0.5 * g.step)
        if len(cand) == 0:
            break
        t.add(npos[cand], nd[cand], grow_ids[cand])
        killed = cKDTree(npos[cand]).query(attr[live], distance_upper_bound=g.kill)[0]
        alive[live[np.isfinite(killed)]] = False
    return it, len(attr)


def _rotate(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rotate v about the unit axis by angle (radians), Rodrigues' formula."""
    c, s = np.cos(angle), np.sin(angle)
    return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1 - c)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _grow_branching(cfg: Config, fields: _Fields, t: _Tree, sep: float,
                    rng: np.random.Generator) -> int:
    """Recursive coral: every root grows a trunk that forks again and again.

    Each fork splits a branch into two whose directions differ by fork_angle, within a fork plane
    through the branch. The plane turns by fork_twist_deg about the branch at every level: 0 keeps
    all forks of a colony in one plane (a sea fan; the first plane faces the host centre, turned by
    up to azimuth_jitter_deg), 90 alternates them (a bushy staghorn that fills space, which leaves
    room for far more branches under the spacing rule). Directions wander by wander_deg per step
    and are always clamped into the tilt cone; children are length_ratio as long as their parent.
    All branches advance one step per iteration, so the spacing rule treats every colony alike.
    """
    g, br = cfg.growth, cfg.branching
    tilt = g.max_tilt_deg
    centre = (fields.host_lo[:2] + fields.host_hi[:2]) / 2
    tips = []
    for i in range(len(t.parent)):
        r = t.P[i]
        az = np.arctan2(*(r[:2] - centre)[::-1]) + np.radians(rng.uniform(-1, 1) * br.azimuth_jitter_deg)
        d = t.D[i].copy()
        fnorm = np.array([np.cos(az), np.sin(az), 0.0])
        fnorm = fnorm - np.dot(fnorm, d) * d
        if np.linalg.norm(fnorm) < 1e-6:                  # root pointing along the radial direction
            fnorm = np.cross(d, _UP) if abs(d[2]) < 0.99 else np.array([1.0, 0.0, 0.0])
        tips.append(dict(node=i, dir=d, target=d, fnorm=_unit(fnorm),
                         left=int(round(br.trunk_length / g.step)), forks=br.max_forks))
    wander = np.radians(br.wander_deg)
    it = 0
    for it in range(1, g.max_iterations + 1):
        if not tips:
            break
        props = []
        for tp in tips:
            if tp["left"] <= 0:
                if tp["forks"] <= 0:
                    continue
                plane_n = _unit(_rotate(tp["fnorm"], tp["dir"], np.radians(br.fork_twist_deg)))
                spread = np.radians(rng.uniform(br.fork_angle_min_deg, br.fork_angle_max_deg))
                bias = rng.uniform(-0.5, 0.5) * spread          # asymmetric forks look grown
                level = br.max_forks - tp["forks"] + 1
                for side in (-1, 1):
                    tgt = clamp_to_cone(_rotate(tp["dir"], plane_n, bias + side * spread / 2), tilt)[0]
                    length = br.trunk_length * br.length_ratio ** level
                    props.append(dict(tp, target=tgt, fnorm=plane_n, forks=tp["forks"] - 1,
                                      left=max(1, int(round(length * rng.uniform(0.8, 1.15) / g.step)))))
            else:
                props.append(dict(tp))
        if not props:
            break
        for tp in props:
            noise = rng.normal(0.0, wander, 3)
            d = tp["dir"] + 0.35 * (tp["target"] - tp["dir"]) + noise
            d = clamp_to_cone(d, tilt)[0]
            f = tp["fnorm"] - np.dot(tp["fnorm"], d) * d
            tp["dir"], tp["fnorm"] = d, (_unit(f) if np.linalg.norm(f) > 1e-6 else tp["fnorm"])
        nd = np.array([tp["dir"] for tp in props])
        par = np.array([tp["node"] for tp in props])
        npos = t.P[par] + g.step * nd
        ok = _node_ok(cfg, fields, npos, t.P[par])
        cand = _separate(np.nonzero(ok)[0], npos, par, cKDTree(t.P), t.anc, t.depth, sep, 0.5 * g.step)
        if len(cand) == 0:
            break
        first = len(t.P)
        t.add(npos[cand], nd[cand], par[cand])
        tips = [dict(props[c], node=first + k, left=props[c]["left"] - 1) for k, c in enumerate(cand)]
    return it


def tube_printable(d: np.ndarray, n: np.ndarray, center_height_ratio: float, max_tilt_deg: float) -> bool:
    """Can a round branch along unit direction d, lying on a surface with unit normal n (its axis
    center_height_ratio radii above the surface), print without its exposed underside overhanging
    more than max_tilt?

    The tube's surface normals u run round a circle perpendicular to d; u is exposed where
    u.n >= -h. The lowest exposed normal lies at an end of that arc or at the circle's own lowest
    point, if the arc contains it.
    """
    a = np.cross(d, _UP if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0]))
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    h = center_height_ratio
    cands = []
    an, bn = np.dot(a, n), np.dot(b, n)
    r = np.hypot(an, bn)
    if r <= h:                       # the whole circle is exposed
        cands_phi = []
        whole = True
    else:
        delta = np.arctan2(bn, an)
        w = np.arccos(-h / r)
        cands_phi = [delta + w, delta - w]
        whole = False
    cands = [np.cos(f) * a + np.sin(f) * b for f in cands_phi]
    zp = _UP - np.dot(_UP, d) * d
    if np.linalg.norm(zp) > 1e-12:
        lowest = -zp / np.linalg.norm(zp)
        if whole or np.dot(lowest, n) >= -h:
            cands.append(lowest)
    if not cands:                    # d vertical: every normal is horizontal
        return True
    return min(u[2] for u in cands) >= -np.sin(np.radians(max_tilt_deg)) - 1e-9


def print_up(cfg: Config, z: np.ndarray) -> np.ndarray:
    """Print-frame up direction (+1 or -1 along Z of the run frame) at heights z: -1 inside a
    [[part]] printed upside down, +1 elsewhere."""
    up = np.ones(len(z))
    for pt in cfg.part:
        if pt.flip:
            up[(z >= pt.z_min) & (z < pt.z_max)] = -1.0
    return up


def _hanging_tips(pos: np.ndarray, nrm: np.ndarray, dirs: np.ndarray, parent: np.ndarray,
                  cfg: Config) -> np.ndarray:
    """Keep-mask without branch ends that would hang: a tip on a surface steeper than the tilt
    cone must point up in the print frame of its piece, or its rounded end overhangs. The whole
    twig back to its fork goes."""
    n = len(parent)
    children = np.zeros(n, dtype=int)
    np.add.at(children, parent[parent >= 0], 1)
    cos_t = np.cos(np.radians(cfg.growth.max_tilt_deg))
    up = print_up(cfg, pos[:, 2])
    bad = (children == 0) & (parent >= 0) & (nrm[:, 2] < cos_t) & (dirs[:, 2] * up < cos_t)
    keep = np.ones(n, dtype=bool)
    for leaf in np.nonzero(bad)[0]:
        i = leaf
        while i >= 0 and children[i] <= 1 and parent[i] >= 0:
            keep[i] = False
            i = parent[i]
    return keep


def _grow_crawl(cfg: Config, fields: _Fields, host: trimesh.Trimesh, t: _Tree, normals: list,
                sep: float, rng: np.random.Generator) -> tuple[int, int]:
    """Coral creeping over the host: space colonisation on the surface.

    Every step is projected onto the tangent plane and snapped to the nearest allowed surface
    sample. Its direction is turned within the tangent plane, as little as possible, until it is
    allowed: the branch lying there must print (tube_printable), and wherever the surface is
    steeper than the tilt cone the coral may only run downwards within the cone. It pours over
    edges and down the sides and never climbs back, so a run down a wall has no low point that
    would hang, whichever way up its piece is printed. The snapped step is checked again.
    """
    g, c, env = cfg.growth, cfg.crawl, cfg.envelope
    pts, face = trimesh.sample.sample_surface_even(host, c.surface_samples, seed=int(rng.integers(2**31)))
    nrm = host.face_normals[face]
    allowed = (fields.keep_dist(pts) >= env.keepout_margin) & (fields.cut_dist(pts) > fields.grid.res)
    S, N = pts[allowed], nrm[allowed]
    if len(S) == 0:
        raise GrowthError("no host surface outside the cut and keep-out volumes")
    surf = cKDTree(S)
    attr = S[rng.choice(len(S), size=min(c.attractor_count, len(S)), replace=False)]
    alive = np.ones(len(attr), dtype=bool)
    turns = np.radians(np.concatenate([[0.0], np.repeat(np.arange(10, 181, 10), 2) * np.tile([1, -1], 18)]))
    cos_t = np.cos(np.radians(g.max_tilt_deg))

    def allowed_dir(d: np.ndarray, n: np.ndarray) -> bool:
        if n[2] < cos_t and d[2] > -cos_t:          # steep surface: only down, within the cone
            return False
        return tube_printable(d, n, c.center_height_ratio, g.max_tilt_deg)

    it = 0
    for it in range(1, g.max_iterations + 1):
        tree = cKDTree(t.P)
        live = np.nonzero(alive)[0]
        if len(live) == 0:
            break
        dist, idx = tree.query(attr[live], distance_upper_bound=g.influence)
        hit = np.isfinite(dist)
        if not hit.any():
            break
        src, a = idx[hit], attr[live[hit]]
        pull = a - t.P[src]
        pull /= np.maximum(np.linalg.norm(pull, axis=1, keepdims=True), 1e-12)
        acc = np.zeros_like(t.P)
        np.add.at(acc, src, pull)
        grow_ids = np.unique(src)
        npos, ndir, nnrm, par = [], [], [], []
        for i in grow_ids:
            n = normals[i]
            v = acc[i] / np.linalg.norm(acc[i]) + g.inertia * t.D[i]
            v = v - np.dot(v, n) * n
            if np.linalg.norm(v) < 1e-9:
                continue
            v /= np.linalg.norm(v)
            for ang in turns:
                d = _rotate(v, n, ang)
                if allowed_dir(d, n):
                    break
            else:
                continue
            raw = t.P[i] + g.step * d
            gap, j = surf.query(raw)
            if gap > c.snap_limit_ratio * g.step:
                continue
            moved = S[j] - t.P[i]
            if np.linalg.norm(moved) < 0.5 * g.step:
                continue
            md = moved / np.linalg.norm(moved)
            if not (allowed_dir(md, n) and allowed_dir(md, N[j])):
                continue
            npos.append(S[j]); ndir.append(md); nnrm.append(N[j]); par.append(i)
        if not npos:
            break
        npos, ndir, par = np.array(npos), np.array(ndir), np.array(par)
        cand = _separate(np.arange(len(npos)), npos, par, tree, t.anc, t.depth, sep, 0.5 * g.step)
        if len(cand) == 0:
            break
        t.add(npos[cand], ndir[cand], par[cand])
        normals.extend(nnrm[k] for k in cand)
        killed = cKDTree(npos[cand]).query(attr[live], distance_upper_bound=g.kill)[0]
        alive[live[np.isfinite(killed)]] = False
    _smooth_paths(t, normals, surf, S, N, c.smooth_iterations)
    _add_polyps(cfg, fields, t, normals, rng)
    return it, len(attr)


def _smooth_paths(t: _Tree, normals: list, surf: cKDTree, S: np.ndarray, N: np.ndarray,
                  iterations: int) -> None:
    """Pull every node inside a path (one parent, one child) halfway to its neighbours' mean, then
    back onto the tangent plane of the nearest surface sample: snapping leaves a jitter along each
    branch that would read as lumps. Roots, forks and tips stay where they are."""
    par = np.array(t.parent)
    n = len(par)
    kids = np.zeros(n, dtype=int)
    np.add.at(kids, par[par >= 0], 1)
    child = np.full(n, -1)
    child[par[par >= 0]] = np.nonzero(par >= 0)[0]
    inner = np.nonzero((par >= 0) & (kids == 1))[0]
    if len(inner) == 0:
        return
    for _ in range(iterations):
        mid = 0.5 * t.P[inner] + 0.25 * (t.P[par[inner]] + t.P[child[inner]])
        _, j = surf.query(mid)
        mid -= np.einsum("ij,ij->i", mid - S[j], N[j])[:, None] * N[j]
        t.P[inner] = mid
        for k, i in enumerate(inner):
            normals[i] = N[j[k]]
    seg = t.P[par >= 0] - t.P[par[par >= 0]]
    t.D[par >= 0] = seg / np.maximum(np.linalg.norm(seg, axis=1, keepdims=True), 1e-12)


def _add_polyps(cfg: Config, fields: _Fields, t: _Tree, normals: list, rng: np.random.Generator) -> None:
    """Short vertical stubs on upward faces: three nodes straight up from a path node, so they
    print like any branch inside the tilt cone and survive the twig pruning."""
    c, g = cfg.crawl, cfg.growth
    cos_t = np.cos(np.radians(g.max_tilt_deg))
    base = [i for i in range(len(t.parent))
            if t.parent[i] >= 0 and normals[i][2] >= cos_t and rng.uniform() < c.polyp_probability]
    for i in base:
        length = rng.uniform(c.polyp_length_min, c.polyp_length_max)
        pts = t.P[i] + np.outer(np.arange(1, 4) / 3 * length, _UP)
        if np.any(fields.keep_dist(pts) < cfg.envelope.keepout_margin):
            continue
        prev = i
        for p in pts:
            t.add(p[None, :], _UP[None, :], np.array([prev]))
            normals.append(normals[i])
            prev = len(t.P) - 1


def grow(cfg: Config) -> tuple[Skeleton, GrowthReport]:
    host = load_mesh(cfg.host.stl)
    g = cfg.growth
    rng = np.random.default_rng(g.random_seed)
    fields = _Fields(cfg, host)
    roots, normals = _seed_roots(cfg, host, fields, rng)
    n_root = len(roots)
    dir0 = clamp_to_cone(normals, g.max_tilt_deg)
    # Unrelated branches keep this far apart (axis to axis) while growing: two touching branches
    # leave a thin web or gap between them whose underside needs support. Growth spaces them by
    # the tip radius; conflict_prune enforces the final radii afterwards.
    sep = 2 * cfg.radius.tip + g.branch_gap
    # Nodes sharing an ancestor within this many steps belong to the same fork and may be closer.
    # It covers the steps two fork branches need to grow the full-radius spacing apart: one step
    # per step length in volume mode, more when fork branches part at fork_angle_min_deg.
    final_sep = 2 * cfg.radius.max + g.branch_gap
    if cfg.envelope.shape == "branching" and cfg.branching.fork_angle_min_deg > 0:
        per_step = g.step * np.sin(np.radians(cfg.branching.fork_angle_min_deg))
    else:
        per_step = g.step
    depth = int(np.ceil(final_sep / per_step)) + 1
    t = _Tree(P=roots.copy(), D=dir0.copy(), parent=[-1] * n_root,
              anc=[(i,) for i in range(n_root)], depth=depth)
    crawl = cfg.envelope.shape == "crawl"
    normals = [nv for nv in normals]
    if crawl:
        t.D[:] = 0.0                            # creeping roots have no preferred heading yet
        it, n_attr = _grow_crawl(cfg, fields, host, t, normals, sep, rng)
    elif cfg.envelope.shape == "volume":
        it, n_attr = _grow_sca(cfg, fields, t, sep, rng)
    else:
        it, n_attr = _grow_branching(cfg, fields, t, sep, rng), 0

    par = np.array(t.parent)
    keep = np.ones(len(par), dtype=bool)
    while True:
        keep &= _expand(prune_twigs(_compact(par, keep)[0], g.min_twig_nodes), keep)
        if crawl:
            keep &= _expand(_hanging_tips(t.P[keep], np.array(normals)[keep], t.D[keep],
                                          _compact(par, keep)[0], cfg), keep)
        par_k, remap = _compact(par, keep)
        radius = pipe_radii(par_k, cfg.radius.tip, cfg.radius.max, cfg.radius.pipe_exponent)
        # Creeping branches always lie on the host, so where two touch the host carries them
        ok = (np.ones(len(par_k), dtype=bool) if crawl
              else conflict_prune(t.P[keep], par_k, radius, depth, g.branch_gap))
        if ok.all() and not (crawl and not _hanging_tips(t.P[keep], np.array(normals)[keep],
                                                         t.D[keep], par_k, cfg).all()):
            break
        keep &= _expand(ok, keep)
    P_k = t.P[keep]
    root_dir = np.zeros_like(P_k)
    root_normal = np.zeros_like(P_k)
    root_ids = np.nonzero(keep[:n_root])[0]
    if crawl:
        # Surface points -> branch axes, lifted by a fraction of each branch's own radius; roots
        # anchor straight down into the host
        nrm_k = np.array(normals)[keep]
        P_k = P_k + nrm_k * (cfg.crawl.center_height_ratio * radius)[:, None]
        root_dir[remap[root_ids]] = nrm_k[remap[root_ids]]
        root_normal[remap[root_ids]] = nrm_k[remap[root_ids]]
    else:
        root_dir[remap[root_ids]] = dir0[root_ids]
        root_normal[remap[root_ids]] = np.array(normals)[root_ids]
    skel = Skeleton(pos=P_k, parent=par_k, radius=radius, root_dir=root_dir, root_normal=root_normal)
    report = GrowthReport(roots=n_root, attractors=n_attr, iterations=it,
                          nodes=int(keep.sum()), pruned=int((~keep).sum()))
    return skel, report

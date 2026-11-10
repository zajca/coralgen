"""coralgen tests.

Run from coralgen/:  uv run python -m unittest discover -s tests -v
The end-to-end test slices the result with PrusaSlicer, so prusa-slicer must be on PATH.
"""
import pathlib
import shutil
import tempfile
import tomllib
import unittest

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from coralgen import config
from coralgen.geometry import to_manifold
from coralgen.grow import (GrowthError, Skeleton, clamp_to_cone, grow, pipe_radii, prune_twigs,
                           root_anchor, tube_printable)
from coralgen.mesh import build
from coralgen.prusa_profile import ProfileError, bed_center, merged_config, parse_bundle, resolve, write_ini
from coralgen.slicecheck import added_supports

# Parameters validated against PrusaSlicer auto-supports (30 deg tilt, 0.25 mm voxel). The host,
# volumes and output paths are filled in per test.
CONFIG_TOML = """
part = []
[host]
stl = "host.stl"
cut_stl = ""
keepout_stl = "keep.stl"

[seed]
count = 10
min_spacing = 6.0
z_min = 8.0
z_max = 16.0
min_normal_z = -0.05
root_embed = 0.5
surface_samples = 6000
max_hull_depth = 0.5

[envelope]
spread = 14.0
height_above_top = 16.0
shape = "volume"
attractor_count = 1500
xy_margin = 14.0
host_clearance = 4.5
keepout_margin = 2.5
field_voxel = 0.5

[branching]
trunk_length = 12.0
length_ratio = 0.8
max_forks = 4
fork_angle_min_deg = 22.0
fork_angle_max_deg = 40.0
wander_deg = 4.0
fork_twist_deg = 0.0
azimuth_jitter_deg = 20.0

[crawl]
surface_samples = 120000
attractor_count = 2500
center_height_ratio = 0.4
snap_limit_ratio = 0.8
smooth_iterations = 4
polyp_probability = 0.12
polyp_length_min = 2.0
polyp_length_max = 4.5

[growth]
step = 1.5
influence = 12.0
kill = 3.0
max_tilt_deg = 30.0
inertia = 0.6
upward_bias = 0.25
max_iterations = 200
min_twig_nodes = 3
branch_gap = 1.5
random_seed = 3

[radius]
tip = 1.4
max = 2.5
pipe_exponent = 2.4

[mesh]
voxel = 0.25
taubin_iterations = 20
preview_sides = 6

[verify]
vendor_bundle = "~/.config/PrusaSlicer/vendor/PrusaResearch.ini"
printer_preset = "Original Prusa MINI & MINI+ Input Shaper"
print_preset = "0.20mm SPEED @MINIIS 0.4"
filament_preset = "Prusament PLA @MINIIS"
support_threshold = 0.0
tolerance = 3.0
z_window = 0.6
max_attempts = 4

[output]
dir = "out"
name = "t"
"""


def raw_config() -> dict:
    return tomllib.loads(CONFIG_TOML)


def related(parent: np.ndarray, i: int, j: int, depth: int) -> bool:
    def chain(k: int) -> set[int]:
        out = set()
        for _ in range(depth):
            out.add(k)
            k = parent[k]
            if k < 0:
                break
        return out
    return bool(chain(i) & chain(j))


class ConfigTest(unittest.TestCase):
    def test_complete_config_loads(self):
        cfg = config.from_dict(raw_config(), pathlib.Path("/base"))
        self.assertEqual(cfg.host.stl, pathlib.Path("/base/host.stl"))
        self.assertIsNone(cfg.host.cut_stl)
        self.assertEqual(cfg.growth.max_tilt_deg, 30.0)

    def test_missing_key_fails(self):
        raw = raw_config()
        del raw["growth"]["step"]
        with self.assertRaisesRegex(config.ConfigError, "missing required key 'step'"):
            config.from_dict(raw, pathlib.Path("/"))

    def test_unknown_key_fails(self):
        raw = raw_config()
        raw["mesh"]["voxle"] = 0.2
        with self.assertRaisesRegex(config.ConfigError, "unknown key"):
            config.from_dict(raw, pathlib.Path("/"))

    def test_gap_must_be_positive(self):
        raw = raw_config()
        raw["growth"]["branch_gap"] = 0.0
        with self.assertRaisesRegex(config.ConfigError, "branch_gap"):
            config.from_dict(raw, pathlib.Path("/"))


class ProfileTest(unittest.TestCase):
    BUNDLE = """
[print:*common*]
layer_height = 0.3
perimeters = 2

[print:fine]
inherits = *common*; *slow*
layer_height = 0.1

[print:*slow*]
perimeters = 3
speed = 20

[print:loop]
inherits = loop2

[print:loop2]
inherits = loop

[printer:p]
bed_shape = 0x0,180x0,180x200,0x200
inherits =
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "bundle.ini"
        self.path.write_text(self.BUNDLE)
        self.sections = parse_bundle(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parents_left_to_right_then_own(self):
        r = resolve(self.sections, "print", "fine")
        self.assertEqual(r["layer_height"], "0.1")    # own key wins
        self.assertEqual(r["perimeters"], "3")        # later parent wins over earlier
        self.assertEqual(r["speed"], "20")

    def test_cycle_and_missing(self):
        with self.assertRaisesRegex(ProfileError, "cycle"):
            resolve(self.sections, "print", "loop")
        with self.assertRaisesRegex(ProfileError, "not found"):
            resolve(self.sections, "print", "nope")

    def test_bed_center(self):
        self.assertEqual(bed_center(resolve(self.sections, "printer", "p")), (90.0, 100.0))


class ConeTest(unittest.TestCase):
    def test_results_stay_in_cone(self):
        rng = np.random.default_rng(0)
        v = rng.normal(size=(500, 3))
        out = clamp_to_cone(v, 30.0)
        np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-9)
        self.assertTrue(np.all(out[:, 2] >= np.cos(np.radians(30.0)) - 1e-9))

    def test_inside_cone_unchanged_and_azimuth_kept(self):
        v = np.array([[0.1, 0.0, 1.0], [1.0, 1.0, -1.0]])
        out = clamp_to_cone(v, 30.0)
        np.testing.assert_allclose(out[0], v[0] / np.linalg.norm(v[0]))
        self.assertAlmostEqual(out[1, 0], out[1, 1])          # azimuth 45 deg preserved
        self.assertAlmostEqual(out[1, 2], np.cos(np.radians(30.0)))

    def test_straight_down_becomes_up(self):
        np.testing.assert_allclose(clamp_to_cone([[0, 0, -1]], 30.0)[0], [0, 0, 1])


class TreeTest(unittest.TestCase):
    #      0 (root)
    #      1
    #    2   4
    #    3   5 - 6 - 7
    PARENT = np.array([-1, 0, 1, 2, 1, 4, 5, 6])

    def test_pipe_model(self):
        r = pipe_radii(self.PARENT, tip=1.0, rmax=10.0, exponent=2.0)
        self.assertEqual(r[3], 1.0)
        self.assertEqual(r[7], 1.0)
        self.assertAlmostEqual(r[1], np.sqrt(2.0))
        self.assertAlmostEqual(r[0], r[1])

    def test_pipe_model_cap(self):
        self.assertLessEqual(pipe_radii(self.PARENT, 1.0, 1.2, 2.0).max(), 1.2)

    def test_prune_short_twig_only(self):
        keep = prune_twigs(self.PARENT, min_nodes=3)
        np.testing.assert_array_equal(keep, [True, True, False, False, True, True, True, True])

    def test_prune_bare_root(self):
        keep = prune_twigs(np.array([-1, -1, 1]), min_nodes=3)
        np.testing.assert_array_equal(keep, [False, True, True])


class CrawlTubeTest(unittest.TestCase):
    """A branch lying on a surface, its axis 0.4 radii above it, against a 40 deg overhang limit."""
    X, Y, Z = np.eye(3)

    def ok(self, d, n):
        return tube_printable(np.asarray(d, float) / np.linalg.norm(d), np.asarray(n, float), 0.4, 40.0)

    def test_on_a_top_face_any_direction(self):
        for d in ([1, 0, 0], [0, 1, 0], [1, 1, 0]):
            self.assertTrue(self.ok(d, self.Z))

    def test_on_a_wall_only_near_vertical(self):
        self.assertTrue(self.ok([0, 0, -1], self.X))
        self.assertTrue(self.ok([0, np.sin(np.radians(30)), -np.cos(np.radians(30))], self.X))
        self.assertFalse(self.ok([0, 1, 0], self.X))          # sideways along a wall hangs
        self.assertFalse(self.ok([0, np.sin(np.radians(60)), -np.cos(np.radians(60))], self.X))

    def test_lower_axis_hides_more_underside(self):
        # Half-sunk branch on a top face: exposed underside reaches 23.6 deg below horizontal
        d = self.X
        self.assertTrue(tube_printable(d, self.Z, 0.4, 25.0))
        self.assertFalse(tube_printable(d, self.Z, 0.4, 20.0))


class RootAnchorTest(unittest.TestCase):
    def test_depth_is_radius_plus_embed(self):
        d = clamp_to_cone([[1.0, 0.0, 0.0]], 30.0)
        a = root_anchor(np.zeros((1, 3)), d, np.array([[1.0, 0.0, 0.0]]), np.array([2.0]), 0.5, 30.0)
        self.assertAlmostEqual(-a[0, 0], 2.5)                  # depth along the wall normal
        np.testing.assert_allclose(np.cross(a[0], d[0]), 0, atol=1e-12)   # collinear with the branch


class EndToEndTest(unittest.TestCase):
    """Synthetic host: box with a keep-out column over one corner."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(cls.tmp.name)
        host = trimesh.creation.box((36, 28, 16))
        host.apply_translation((0, 0, 8))
        host.export(d / "host.stl")
        keep = trimesh.creation.box((12, 12, 100))
        keep.apply_translation((18, 14, 50))
        keep.export(d / "keep.stl")
        cls.dir = d
        cls.cfg = config.from_dict(raw_config(), d)
        cls.skel, cls.report = grow(cls.cfg)
        cls.result, cls.coral, cls.mesh_report = build(cls.cfg, cls.skel)
        cls.result_path = d / "result.stl"
        cls.result.export(cls.result_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_grew_something(self):
        self.assertGreater(self.report.nodes, 50)

    def test_every_segment_within_cone(self):
        child = np.nonzero(self.skel.parent >= 0)[0]
        seg = self.skel.pos[child] - self.skel.pos[self.skel.parent[child]]
        tilt = np.degrees(np.arccos(seg[:, 2] / np.linalg.norm(seg, axis=1)))
        self.assertLessEqual(tilt.max(), self.cfg.growth.max_tilt_deg + 1e-6)

    def test_tips_have_minimum_radius(self):
        self.assertAlmostEqual(self.skel.radius.min(), self.cfg.radius.tip)

    def test_unrelated_branches_keep_gap(self):
        # Volume mode: the relation window is one node per step length of the full spacing
        g = self.cfg.growth
        depth = int(np.ceil((2 * self.cfg.radius.max + g.branch_gap) / g.step)) + 1
        r = self.skel.radius
        for i, j in cKDTree(self.skel.pos).query_pairs(2 * r.max() + g.branch_gap):
            if related(self.skel.parent, i, j, depth):
                continue
            d = np.linalg.norm(self.skel.pos[i] - self.skel.pos[j])
            self.assertGreaterEqual(d, r[i] + r[j] + g.branch_gap, f"nodes {i} and {j} too close")

    def test_result_is_closed_manifold(self):
        self.assertTrue(self.result.is_watertight)
        to_manifold(self.result, "result")      # raises if manifold3d rejects it

    def test_result_fuses_host(self):
        host = trimesh.load(self.dir / "host.stl")
        self.assertGreater(self.mesh_report.result_volume, host.volume + 100)
        self.assertEqual(len(self.result.split(only_watertight=False)), 1)

    def test_no_coral_in_keepout(self):
        # The keep-out overlaps a corner of the host on purpose; only grown material counts
        keep = to_manifold(trimesh.load(self.dir / "keep.stl"), "keep")
        inter = to_manifold(self.coral, "coral") ^ keep
        self.assertLess(inter.volume(), 1e-3)

    def test_nothing_below_bed(self):
        self.assertGreaterEqual(self.result.bounds[0][2], -1e-6)

    def test_deterministic(self):
        again, _ = grow(self.cfg)
        np.testing.assert_array_equal(again.parent, self.skel.parent)
        np.testing.assert_allclose(again.pos, self.skel.pos)

    def test_skeleton_roundtrip(self):
        path = self.dir / "skel.json"
        self.skel.save(path)
        back = Skeleton.load(path)
        np.testing.assert_array_equal(back.parent, self.skel.parent)
        np.testing.assert_allclose(back.pos, self.skel.pos, atol=1e-4)

    def test_prusaslicer_adds_no_support(self):
        # Regression pin for this seed and host, sliced with the user's MINI+ system presets.
        # A pass here is not proof that every generated coral prints unsupported; that is what
        # `coralgen search` checks per result.
        self.assertIsNotNone(shutil.which("prusa-slicer"), "prusa-slicer must be on PATH")
        v = self.cfg.verify
        self.assertTrue(v.vendor_bundle.exists(), f"{v.vendor_bundle} is required")
        prof = merged_config(v.vendor_bundle, v.print_preset, v.printer_preset, v.filament_preset)
        ini = self.dir / "profile.ini"
        write_ini(prof, ini)
        rep = added_supports(self.result_path, self.dir / "host.stl", ini, v.support_threshold,
                             v.tolerance, v.z_window, bed_center(prof))
        self.assertEqual(rep.added_points, 0, rep)

    def test_gate_detects_a_cantilever(self):
        # The gate itself must fail an obviously unsupported part with the same profile
        v = self.cfg.verify
        prof = merged_config(v.vendor_bundle, v.print_preset, v.printer_preset, v.filament_preset)
        ini = self.dir / "profile.ini"
        write_ini(prof, ini)
        base = trimesh.creation.box((20, 20, 10))
        base.apply_translation((0, 0, 5))
        slab = trimesh.creation.box((40, 20, 3))
        slab.apply_translation((10, 0, 11.5))
        base.export(self.dir / "cant_base.stl")
        trimesh.util.concatenate([base, slab]).export(self.dir / "cant.stl")
        rep = added_supports(self.dir / "cant.stl", self.dir / "cant_base.stl", ini,
                             v.support_threshold, v.tolerance, v.z_window, bed_center(prof))
        self.assertGreater(rep.added_points, 0)

    def test_branching_mode_forks_within_cone(self):
        raw = raw_config()
        raw["envelope"]["shape"] = "branching"
        raw["seed"]["min_normal_z"] = 0.95          # colonies from the top face
        raw["seed"]["z_min"], raw["seed"]["z_max"] = 15.9, 16.1
        raw["seed"]["count"] = 3
        raw["seed"]["min_spacing"] = 12.0
        raw["envelope"]["height_above_top"] = 30.0
        raw["branching"]["trunk_length"] = 6.0
        cfg = config.from_dict(raw, self.dir)
        skel, rep = grow(cfg)
        child = np.nonzero(skel.parent >= 0)[0]
        seg = skel.pos[child] - skel.pos[skel.parent[child]]
        tilt = np.degrees(np.arccos(seg[:, 2] / np.linalg.norm(seg, axis=1)))
        self.assertLessEqual(tilt.max(), cfg.growth.max_tilt_deg + 1e-6)
        kids = np.bincount(skel.parent[child], minlength=len(skel.parent))
        self.assertGreater((kids == 2).sum(), 0, "no fork grew")

    def test_impossible_band_reports_filters(self):
        raw = raw_config()
        raw["seed"]["z_min"], raw["seed"]["z_max"] = 1.0, 2.0     # anchors would leave via the bed
        cfg = config.from_dict(raw, self.dir)
        with self.assertRaisesRegex(GrowthError, "root anchor inside material: 0"):
            grow(cfg)


if __name__ == "__main__":
    unittest.main()
